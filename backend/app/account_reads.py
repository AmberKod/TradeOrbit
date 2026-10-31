"""Manual authenticated account reads, scoped snapshots and credential-version fencing."""

import asyncio
import copy
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import InvalidToken
from redis.exceptions import WatchError
from sqlalchemy import select

from app.core.errors import AppError
from app.core.security import CredentialCipher, aware_utc
from app.db import Runtime
from app.exchanges.private_adapter import normalize
from app.exchanges.private_contracts import PrivateReadError
from app.exchanges.private_http import PrivateHTTP, scopes_for
from app.models.account_state import AccountReadState
from app.models.accounts import AccountConnection, EncryptedCredential
from app.models.identity import AuditLog

ERROR_MESSAGES = {
    "ACCOUNT_MODE_TRANSITION": "账户正在升级或切换模式，请完成切换后重试",
    "UNSUPPORTED_REGION": "本增量仅支持 GLOBAL 地区；不会将其他地区密钥发送到全球站",
    "UNSUPPORTED_ENVIRONMENT": "账户环境尚未支持",
    "BINANCE_DEMO_NOT_SUPPORTED": "币安现货测试网与合约模拟密钥相互独立，本增量暂不接入币安 DEMO",
    "ACCOUNT_MODE_REQUIRED": "请使用明确的账户模式新建连接，UNKNOWN 不会自动猜测",
    "ACCOUNT_MODE_MISMATCH": "交易所返回的账户模式与当前接入范围不匹配",
    "CREDENTIALS_REQUIRED": "请先保存对应环境的 API 密钥",
    "CREDENTIAL_UNAVAILABLE": "后端无法解密此凭据，请检查加密密钥版本或重新保存密钥",
    "AUTH_OR_PERMISSION": "认证或权限校验失败，请检查密钥、Passphrase、环境和 IP 白名单",
    "SIGNATURE_REJECTED": "签名被拒绝，本增量支持 HMAC 密钥，请检查密钥类型与 Secret",
    "ACCESS_RESTRICTED": "访问受限，请检查地区、IP 白名单和交易所限制",
    "CLOCK_SKEW": "交易所拒绝请求时间，已校时重试一次，请检查主机时钟",
    "CLOCK_UNRELIABLE": "主机时钟偏差或校时延迟过大，请检查系统时间和网络",
    "NETWORK_ERROR": "无法连接交易所，请检查后端网络和独立私有代理配置",
    "TIMEOUT": "读取交易所超时，已保留此凭据版本的旧快照",
    "RATE_LIMITED": "交易所限流，系统进入冷却期，请稍后重试",
    "IP_BANNED": "交易所暂时封禁访问 IP，系统已停止本轮后续请求并冷却",
    "EXCHANGE_UNAVAILABLE": "交易所暂不可用",
    "EXCHANGE_REJECTED": "交易所拒绝此只读请求，请核查账户模式和产品权限",
    "INVALID_RESPONSE": "交易所响应不符合当前契约，未覆盖已有快照",
    "INCOMPLETE_RESPONSE": "响应仍有未覆盖的分页，未将不完整持仓保存为完整快照",
    "INVALID_CREDENTIAL_FORMAT": "密钥格式不受支持，请使用无换行的 HMAC API 凭据",
    "READ_ROUTE_NOT_ALLOWED": "该私有读取路径未获授权",
}


def describe_error(code: str | None) -> str | None:
    return ERROR_MESSAGES.get(code or "", "本轮只读同步失败") if code else None


def profile_error(account: AccountConnection) -> str | None:
    try:
        scopes_for(
            account.exchange, account.environment, account.account_mode, account.region_profile
        )
    except PrivateReadError as exc:
        return exc.code
    return None


def render_state(
    account: AccountConnection, record: AccountReadState | None, *, include_data: bool = True
) -> dict[str, Any]:
    unsupported = profile_error(account)
    if record is not None and record.credential_version != account.credential_version:
        record = None
    result: dict[str, Any] = {
        "account_id": str(account.id),
        "credential_version": account.credential_version,
        "state": record.state if record else "NOT_VERIFIED",
        "trading_enabled": False,
        "sync_supported": unsupported is None,
        "sync_block_reason": describe_error(unsupported),
        "checked_at": aware_utc(record.checked_at).isoformat() if record else None,
        "transport": "MANUAL_REST",
        "stale_after_seconds": 300,
        "scopes": {},
    }
    if record is None:
        return result
    now = datetime.now(UTC)
    for name, saved in record.scopes.items():
        item = copy.deepcopy(saved)
        observed = datetime.fromisoformat(item["observed_at"]) if item.get("observed_at") else None
        age = max(0, int((now - aware_utc(observed)).total_seconds())) if observed else None
        item["age_seconds"] = age
        item["freshness"] = (
            "MISSING"
            if observed is None
            else "FRESH"
            if item["status"] == "OK" and age is not None and age <= 300
            else "STALE"
        )
        item["error_message"] = describe_error(item.get("error_code"))
        if not include_data:
            item.pop("data", None)
        result["scopes"][name] = item
    return result


class PrivateReadService:
    def __init__(self, runtime: Runtime, client: httpx.AsyncClient):
        self.runtime, self.client = runtime, client

    async def _unlock(self, key: str, token: str) -> None:
        async with self.runtime.redis.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(key)
                value = await pipe.get(key)
                if value not in (token, token.encode()):
                    await pipe.unwatch()
                    return
                pipe.multi()
                pipe.delete(key)
                await pipe.execute()
            except WatchError:
                pass

    async def sync(
        self, account_id: UUID, workspace_id: UUID, actor_id: UUID, request_id: str
    ) -> dict[str, Any]:
        async with self.runtime.sessions() as db:
            account = await db.scalar(
                select(AccountConnection).where(
                    AccountConnection.id == account_id,
                    AccountConnection.workspace_id == workspace_id,
                    AccountConnection.status != "ARCHIVED",
                )
            )
            if account is None:
                raise AppError("NOT_FOUND", "账户连接不存在", 404)
            reason = profile_error(account)
            if reason:
                raise AppError(reason, describe_error(reason) or "不支持此配置", 422)
            record = await db.get(EncryptedCredential, account.id)
            if record is None or not account.credential_version:
                raise AppError("CREDENTIALS_REQUIRED", ERROR_MESSAGES["CREDENTIALS_REQUIRED"], 409)
            settings = self.runtime.settings
            try:
                credentials = CredentialCipher(
                    settings.credential_encryption_key.get_secret_value(),
                    settings.encryption_key_version,
                ).decrypt(record.ciphertext, record.key_version)
            except (InvalidToken, ValueError, TypeError, UnicodeError):
                raise AppError(
                    "CREDENTIAL_UNAVAILABLE", ERROR_MESSAGES["CREDENTIAL_UNAVAILABLE"], 409
                ) from None
            exchange, environment, mode, region = (
                account.exchange,
                account.environment,
                account.account_mode,
                account.region_profile,
            )
            version = account.credential_version
        lock = f"private:lock:{workspace_id}:{account_id}"
        token = str(uuid4())
        if not await self.runtime.redis.set(lock, token, nx=True, ex=90):
            raise AppError("SYNC_IN_PROGRESS", "此账户正在同步，请等待本轮完成", 409)
        try:
            cooldown = f"private:cooldown:{workspace_id}:{account_id}"
            blocked = f"private:blocked:{exchange}"
            if await self.runtime.redis.exists(blocked):
                raise AppError("RATE_LIMITED", ERROR_MESSAGES["RATE_LIMITED"], 429)
            if not await self.runtime.redis.set(cooldown, "1", nx=True, ex=30):
                raise AppError("SYNC_COOLDOWN", "每个账户至少间隔 30 秒再同步", 429)
            budget = f"private:budget:{exchange}:{int(time.time() // 60)}"
            count = await self.runtime.redis.incr(budget)
            if count == 1:
                await self.runtime.redis.expire(budget, 120)
            if count > 30:
                raise AppError("RATE_LIMITED", "当前交易所同步预算已用完，请稍后重试", 429)
            started_at = datetime.now(UTC)
            scopes = scopes_for(exchange, environment, mode, region)
            outcomes: dict[str, dict[str, Any]] = {}
            try:
                transport = PrivateHTTP(
                    self.client, exchange, environment, mode, region, credentials
                )
            except PrivateReadError as exc:
                outcomes = {scope: {"status": "FAILED", "error_code": exc.code} for scope in scopes}
            else:
                deadline = time.monotonic() + 45
                stopped: str | None = None
                for scope in scopes:
                    try:
                        if stopped:
                            raise PrivateReadError(stopped)
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise PrivateReadError("TIMEOUT")
                        body = await asyncio.wait_for(transport.get(scope), timeout=remaining)
                        snapshot = normalize(exchange, scope, body)
                        outcomes[scope] = {
                            "status": "OK",
                            "error_code": None,
                            "observed_at": datetime.now(UTC).isoformat(),
                            "data": snapshot.as_dict(),
                        }
                    except (PrivateReadError, TimeoutError) as exc:
                        code = exc.code if isinstance(exc, PrivateReadError) else "TIMEOUT"
                        outcomes[scope] = {"status": "FAILED", "error_code": code}
                        if scope in {"uta_config", "account_config"}:
                            stopped = code
                        if code in {"IP_BANNED", "RATE_LIMITED"}:
                            stopped = code
                            seconds = (
                                max(3600 if code == "IP_BANNED" else 120, exc.retry_after or 0)
                                if isinstance(exc, PrivateReadError)
                                else 120
                            )
                            await self.runtime.redis.set(blocked, code, nx=True, ex=seconds)
                            await self.runtime.redis.expire(blocked, seconds, gt=True)
                for outcome in outcomes.values():
                    if outcome["status"] == "OK":
                        outcome["data"]["metadata"]["clock_offsets_ms"] = (
                            transport.clock_offsets_ms.copy()
                        )
            # No ORM object or transaction from before network I/O is reused here.
            async with self.runtime.sessions() as db:
                account = await db.scalar(
                    select(AccountConnection)
                    .where(
                        AccountConnection.id == account_id,
                        AccountConnection.workspace_id == workspace_id,
                        AccountConnection.status != "ARCHIVED",
                    )
                    .with_for_update()
                )
                if account is None or account.credential_version != version:
                    raise AppError("ACCOUNT_CHANGED", "账户已归档或密钥已变更，本轮结果已丢弃", 409)
                saved = await db.get(AccountReadState, account_id)
                if (
                    saved is not None
                    and saved.credential_version == version
                    and aware_utc(saved.checked_at) >= started_at
                ):
                    raise AppError("STALE_SYNC_RESULT", "已有更新的同步结果，本轮旧结果已丢弃", 409)
                previous = (
                    saved.scopes
                    if saved is not None and saved.credential_version == version
                    else {}
                )
                merged = {}
                for scope, outcome in outcomes.items():
                    if outcome["status"] == "FAILED":
                        old = previous.get(scope, {})
                        outcome = {
                            **outcome,
                            "observed_at": old.get("observed_at"),
                            "data": old.get("data"),
                        }
                    merged[scope] = outcome
                passed = sum(item["status"] == "OK" for item in outcomes.values())
                state = "VERIFIED" if passed == len(scopes) else "PARTIAL" if passed else "FAILED"
                if saved is None:
                    saved = AccountReadState(
                        account_id=account_id,
                        credential_version=version,
                        state=state,
                        scopes=merged,
                    )
                    db.add(saved)
                else:
                    saved.credential_version, saved.state, saved.scopes = version, state, merged
                saved.checked_at = datetime.now(UTC)
                account.status = (
                    "READ_READY" if state == "VERIFIED" else "DEGRADED" if passed else "READ_FAILED"
                )
                db.add(
                    AuditLog(
                        workspace_id=workspace_id,
                        actor_id=actor_id,
                        action="account.read_sync",
                        target_id=str(account_id),
                        request_id=request_id,
                        details={
                            "credential_version": version,
                            "state": state,
                            "scopes": {
                                k: {"status": v["status"], "error_code": v["error_code"]}
                                for k, v in outcomes.items()
                            },
                        },
                    )
                )
                await db.commit()
                return render_state(account, saved)
        finally:
            credentials.clear()
            await self._unlock(lock, token)
