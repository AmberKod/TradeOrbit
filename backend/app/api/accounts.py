"""Role-protected connection CRUD; no exchange traffic or trading in E01."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import Administrator, CurrentIdentity, Database, runtime
from app.core.errors import AppError, success
from app.core.security import CredentialCipher, aware_utc
from app.models.accounts import AccountConnection, EncryptedCredential
from app.models.identity import AuditLog
from app.schemas.accounts import AccountCreate, AccountUpdate, CredentialInput

router = APIRouter(prefix="/accounts", tags=["accounts"])


def serialize(account: AccountConnection) -> dict[str, Any]:
    return {
        "id": str(account.id),
        "label": account.label,
        "exchange": account.exchange,
        "environment": account.environment,
        "account_mode": account.account_mode,
        "region_profile": account.region_profile,
        "status": account.status,
        "credentials_configured": account.credential_version > 0,
        "credential_version": account.credential_version,
        "created_at": aware_utc(account.created_at).isoformat(),
        "updated_at": aware_utc(account.updated_at).isoformat(),
        "capability_state": "NOT_VERIFIED",
    }


async def scoped_account(
    account_id: UUID, workspace_id: UUID, db: Database, *, for_update: bool = False
) -> AccountConnection:
    statement = select(AccountConnection).where(
        AccountConnection.id == account_id,
        AccountConnection.workspace_id == workspace_id,
        AccountConnection.status != "ARCHIVED",
    )
    account = await db.scalar(statement.with_for_update() if for_update else statement)
    if account is None:
        raise AppError("NOT_FOUND", "账户连接不存在", 404)
    return account


def audit(
    request: Request,
    current: Administrator,
    db: Database,
    action: str,
    account_id: UUID,
    details: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            workspace_id=current.workspace_id,
            actor_id=current.user.id,
            action=action,
            target_id=str(account_id),
            request_id=request.state.request_id,
            details=details,
        )
    )


@router.get("")
async def list_accounts(request: Request, current: CurrentIdentity, db: Database) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(AccountConnection)
            .where(
                AccountConnection.workspace_id == current.workspace_id,
                AccountConnection.status != "ARCHIVED",
            )
            .order_by(AccountConnection.created_at.desc())
        )
    ).all()
    return success(request, [serialize(row) for row in rows])


@router.post("", status_code=201)
async def create_account(
    payload: AccountCreate, request: Request, current: Administrator, db: Database
) -> dict[str, Any]:
    account = AccountConnection(workspace_id=current.workspace_id, **payload.model_dump())
    db.add(account)
    await db.flush()
    audit(
        request,
        current,
        db,
        "account.created",
        account.id,
        {"exchange": account.exchange, "environment": account.environment},
    )
    await db.commit()
    return success(request, serialize(account))


@router.get("/{account_id}")
async def read_account(
    account_id: UUID, request: Request, current: CurrentIdentity, db: Database
) -> dict[str, Any]:
    return success(request, serialize(await scoped_account(account_id, current.workspace_id, db)))


@router.patch("/{account_id}")
async def update_account(
    account_id: UUID, payload: AccountUpdate, request: Request, current: Administrator, db: Database
) -> dict[str, Any]:
    account = await scoped_account(account_id, current.workspace_id, db, for_update=True)
    account.label = payload.label
    audit(request, current, db, "account.updated", account.id, {"fields": ["label"]})
    await db.flush()
    await db.commit()
    return success(request, serialize(account))


@router.delete("/{account_id}")
async def archive_account(
    account_id: UUID, request: Request, current: Administrator, db: Database
) -> dict[str, Any]:
    account = await scoped_account(account_id, current.workspace_id, db, for_update=True)
    account.status = "ARCHIVED"
    audit(request, current, db, "account.archived", account.id, {})
    await db.commit()
    return success(request, {"id": str(account_id), "archived": True})


@router.post("/{account_id}/credentials")
async def save_credentials(
    account_id: UUID,
    payload: CredentialInput,
    request: Request,
    current: Administrator,
    db: Database,
) -> dict[str, Any]:
    account = await scoped_account(account_id, current.workspace_id, db, for_update=True)
    if account.exchange in {"bitget", "okx"} and (
        payload.passphrase is None or not payload.passphrase.get_secret_value().strip()
    ):
        raise AppError("PASSPHRASE_REQUIRED", "Bitget 和 OKX 需要 Passphrase", 422)
    values = {
        "api_key": payload.api_key.get_secret_value(),
        "secret": payload.secret.get_secret_value(),
    }
    if not all(value.strip() for value in values.values()):
        raise AppError("INVALID_CREDENTIALS", "密钥不能为空白", 422)
    if payload.passphrase is not None:
        values["passphrase"] = payload.passphrase.get_secret_value()
    settings = runtime(request).settings
    cipher = CredentialCipher(
        settings.credential_encryption_key.get_secret_value(), settings.encryption_key_version
    )
    record = await db.get(EncryptedCredential, account.id)
    if record is None:
        record = EncryptedCredential(
            account_id=account.id, ciphertext=cipher.encrypt(values), key_version=cipher.version
        )
        db.add(record)
    else:
        record.ciphertext, record.key_version = cipher.encrypt(values), cipher.version
    account.credential_version += 1
    account.status = "CONFIGURED"
    audit(
        request,
        current,
        db,
        "account.credentials_saved",
        account.id,
        {"version": account.credential_version, "key_version": cipher.version},
    )
    await db.flush()
    await db.commit()
    return success(
        request,
        {
            "id": str(account.id),
            "credentials_configured": True,
            "credential_version": account.credential_version,
            "capability_state": "NOT_VERIFIED",
        },
    )


@router.get("/{account_id}/capabilities")
async def capabilities(
    account_id: UUID, request: Request, current: CurrentIdentity, db: Database
) -> dict[str, Any]:
    account = await scoped_account(account_id, current.workspace_id, db)
    return success(
        request,
        {
            "account_id": str(account.id),
            "state": "NOT_VERIFIED",
            "trading_enabled": False,
            "reason": "E01 仅保存连接配置，交易所探测与同步在 E02 实现",
        },
    )
