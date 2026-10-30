# E01 基础工程验收记录

执行日期：2026-10-30（Asia/Shanghai）。基线文档提交 5e4a436；后端提交 e9d6a7e、前端提交 98d90e2、部署提交 42eb08e。实现与文档按批次提交，完整记录以 git log 为准；本轮未推送远端。

## 1. 交付范围与状态

E01 = DONE（本地验收）：基础工程、自动化检查、真实依赖、完整容器部署和登录页浏览器验证通过。该结论不等于 V0.1 只读产品已完成，也不表示三所连接通过。

已实现：FastAPI 工厂入口、配置校验、PostgreSQL/Redis runtime、7 张基础表和首个迁移；Opaque cookie 会话、Argon2、会话绑定 CSRF、Origin 白名单、Redis 登录限流；ADMIN/TRADER/VIEWER、工作空间过滤；连接配置 CRUD、Fernet 凭据加密、版本与审计；Vue 页面和错误/空态；独立心跳 Worker；Compose、Dockerfile、Nginx 和 CI。

核心安全决策：交易启用配置被拒绝；没有订单、提币或转账路由；所有连接能力 NOT_VERIFIED；前端未知资产显示 —；密码/密钥不存 localStorage、不回传、不入日志。

## 2. 环境

Windows；Python 3.12.12 / uv 0.9.5；Node 22.20.0 / npm 11.6.2；Docker 29.9.2；PostgreSQL 17、Redis 7.4。前端 Vite 7.3.7 / Vitest 5.0.5，实际全量依赖以 uv.lock 和 package-lock.json 为准。

真实依赖验证使用随机后缀的独立本机数据库，仅写入 fixture-only 凭据及随机测试密码。结束后删除本次创建的验证数据库；正式应用数据库未写入测试账户。没有使用用户真实交易所凭据。

## 3. 已执行检查

| 检查 | 结果 | 证据 / 说明 |
|---|---|---|
| 后端 Ruff lint / format | PASS | ruff check .；ruff format --check .，29 个 Python 文件 |
| 后端类型 | PASS | mypy，22 个 app 源文件无错误 |
| 后端自动化测试 | PASS | pytest -q：21 passed |
| 后端依赖锁 | PASS | uv lock --check，55 packages |
| 前端 lint / typecheck | PASS | npm run lint；npm run typecheck |
| 前端测试 | PASS | 3 个测试文件，8 passed |
| 前端生产构建 | PASS | npm run build，55 modules，按页面拆分加载 |
| 前端依赖漏洞审计 | PASS | npm 官方 registry；0 info/low/moderate/high/critical；仅表示本次查询结果 |
| 真实迁移 | PASS | upgrade head → alembic check 无差异 → downgrade base → upgrade head |
| 真实 API 与角色 | PASS | 独立 PostgreSQL + 实际 Redis；CLI 管理员引导；查看、写入和审计权限 |
| 凭据并发更新 | PASS | 三所分别同时保存两次，版本均为 1、2，无覆盖丢失或唯一键冲突 |
| 重启持久化 | PASS | 重启本项目 db/cache 后，验证数据库的 3 个归档连接与 2 个用户仍在 |
| 完整容器启动 | PASS | docker compose up -d --build；db/cache/API/worker/frontend 均 healthy，migrate 退出 0 |
| 浏览器视觉检查 | PASS（登录页） | 独立 Chrome，1440×1000 / 390×844；无横向溢出和 Runtime exception；不等于全流程浏览器 E2E |
| 远端 CI | NOT_RUN | 已提供工作流，未推送，不声称 GitHub Actions 已执行 |

安全回归覆盖：未登录拒绝；过期/注销会话拒绝；撤销工作空间成员后会话失效；观察者/交易员不能修改；跨工作空间读取/修改返回 404；无 CSRF / 非 ASCII CSRF / 不可信 Origin 被拒绝；拒绝响应保留 no-store、nosniff、请求编号；加密错误密钥失败；响应/验证异常/审计不泄漏 fixture secret；Bitget/OKX 必需 passphrase；交易配置 fail closed；前端注销和旧异步响应不会恢复上个会话的账户缓存。

完整部署补充：通过 Nginx 请求首页返回 200、readiness 返回 READY（database/schema/redis）；CSP 存在；API uid=10001、前端 uid=101；Worker 心跳检查退出 0。截图与视口检查 JSON 保存在被 Git 忽略的 .local，未包含登录密码、密钥或 Cookie。完整认证后的浏览器操作链尚未做端到端自动化，API 权限链已做真实依赖验收。

## 4. 本轮修复

- 补齐 Pydantic/mypy 类型配置与结构化日志处理器类型，明确 UTC 时间序列化。
- 使用 PostgreSQL 行锁序列化凭据更新和归档/重命名竞争，避免版本丢失。
- 修复 Origin 拒绝响应缺失通用安全头以及非 ASCII CSRF 造成服务错误。
- 清理前端跨会话缓存，并忽略过期异步响应。
- 将有漏洞的旧 Vitest 升级到兼容的 5.0.5，重新运行全部前端检查和审计。
- 修正本地 Compose 网络；当前 Docker 的 internal 网络不发布宿主机映射端口，因此本地采用独立普通数据网络，仍仅绑定回环地址。生产网络策略需另行设计。

## 5. 验收口径与后续边界

TC-01 在 E01 范围内通过；DEMO/LIVE 是不可重命名变更的配置维度，实际 API 域名、凭据权限与三所请求隔离留待 E02。TC-02 及其他真实行情/资产/交易场景均 NOT_RUN。重启持久化不等于数据库备份恢复，TC-17 仍未完成。

本轮未执行：交易所公开/私有 API、WebSocket、订单、真实资产同步、策略、告警发送、提币/划转、生产部署、负载测试、后端依赖漏洞专项审计。测试没有代替真实三所验收。

生产前待补：MFA/密码重置、会话清理、密钥轮换、最小权限数据库账号、Redis 认证、TLS/可信代理、备份恢复、审计防篡改等。当前是个人或可信小团队的本地开发基础，不能直接公开托管。

## 6. 复现入口

先阅读 [本地运行手册](07-local-development.md)。自动化检查由 .github/workflows/ci.yml 定义；真实依赖验收运行 backend/scripts/validate_foundation.py，默认不重启服务，可显式传 --restart-data-services 验证本地持久化。脚本只允许回环地址并仅清理自己创建的随机验证数据库。
