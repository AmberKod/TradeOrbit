# TradeOrbit 本地开发与运行手册

日期：2026-10-31。当前完成 E01、E02-M1 公开行情与 E02-M2.1 手动私有只读快照。私有持续同步、聚合净值、告警发送和下单尚未实现。保存账户配置或密钥后仍为 NOT_VERIFIED，管理员点击“验证并同步”才请求交易所。

## 1. 前置条件与目录

- Git、Python 3.12、uv 0.9.5、Node.js 22.12+、npm、Docker Compose v2；Docker daemon 需要运行。
- backend：FastAPI、会话认证、账户配置、加密、审计、Alembic、独立 worker 入口。
- frontend：Vue 3、TypeScript、Pinia、Vue Router、Vite。
- workers：worker 职责说明；infra：部署边界说明；compose.yaml：本地编排入口。
- backend/uv.lock 与 frontend/package-lock.json 固定依赖；不要直接依赖下载目录里的参考源码。

以下命令在仓库根目录运行，示例兼容 PowerShell；分别开终端运行长期进程。

## 2. 首次配置

~~~powershell
uv sync --directory backend --extra dev --frozen
uv run --directory backend python -m app.cli init-env
~~~

init-env 只在根目录不存在 .env 时生成随机 PostgreSQL 密码、会话密钥和 Fernet 加密密钥，不打印秘密，也不覆盖已有配置。.env 已由 .gitignore 排除。不要提交、粘贴进聊天或共享日志；Windows 下还需按实际用户/服务身份限制文件 ACL。

如果本机默认 npm 镜像的依赖同步不完整，可以显式使用官方 registry 安装；不要修改全局 registry 或禁用 TLS 校验。

~~~powershell
npm --prefix frontend ci --registry=https://registry.npmjs.org
~~~

## 3. 容器方式运行

~~~powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose exec backend python -m app.cli bootstrap-admin --email your-email@example.com
~~~

最后一条命令交互式输入两次密码（12–128 字符）。没有内置账户或默认密码。首次引导仅允许空工作空间数据库；后续添加用户用 create-user，显式提供 workspace-id 和 ADMIN/TRADER/VIEWER 角色。

浏览器打开 http://localhost:18080 。API 端口为 127.0.0.1:18000；PostgreSQL 为 127.0.0.1:15432；Redis 为 127.0.0.1:16379。全部仅绑定本机。浏览器经 Nginx 使用同源 /api；Nginx 使用非 root 镜像并设置 CSP、禁止嵌入等响应头。

启动链为 PostgreSQL 健康 → migrate 一次性迁移成功 → API/worker → 前端。API 启动不自动建表。market-worker 启动会获取三所公开产品目录，按工作空间自选订阅；API 在已登录用户请求详情时访问固定官方公开 REST 接口。容器中的数据库/Redis 地址由 Compose 覆盖，宿主机 .env 仍使用回环地址。

~~~powershell
docker compose logs --tail 100 backend worker market-worker migrate
docker compose stop
docker compose start
~~~

日常停止可以 stop 或 down；命名卷会保留数据。不要使用 down -v，它会删除数据。配置变更或迁移后用 up -d --build，不能把普通 start 当作升级流程。

## 4. 宿主机开发方式

先启动依赖并显式迁移、创建管理员：

~~~powershell
docker compose up -d db cache
uv run --directory backend alembic upgrade head
uv run --directory backend python -m app.cli bootstrap-admin --email your-email@example.com
uv run --directory backend uvicorn app.main:create_app --factory --host 127.0.0.1 --port 18000 --reload --no-access-log
~~~

行情采集可保留在容器中运行：docker compose up -d --build market-worker。它与宿主机 API 使用同一 PostgreSQL/Redis 的自选和公开缓存，不需要向采集进程提供账户密钥。

另开终端：

~~~powershell
npm --prefix frontend run dev
~~~

打开 http://localhost:5173 。不要同时启动占用 18000 的容器 API。Vite 的 /api 代理保留 Origin；后端要求所有修改请求携带白名单 Origin，登录成功后的修改还必须带当前会话的 X-CSRF-Token。直接 curl/脚本调用也要满足这些条件。

## 5. 可用功能与接口

- 登录、会话恢复、退出：/api/v1/auth/login、session、logout。Cookie 为 HttpOnly/SameSite=Lax；数据库只存令牌哈希，CSRF 令牌仅在前端内存中保存。
- 账户连接：GET/POST /api/v1/accounts；GET/PATCH/DELETE /accounts/{id}，PATCH 当前仅允许名称；DELETE 是归档。环境、交易所、账户模式不能通过重命名接口更改。
- 密钥：POST /accounts/{id}/credentials；Fernet 加密且带 key_version；不提供明文读取接口，Bitget/OKX 必须有 passphrase。账户配置与密钥变更只允许 ADMIN；TRADER/VIEWER 当前均只读。归档保留历史记录，不会向交易所撤销 API Key，若要吊销请去交易所操作。
- 手动只读：POST /accounts/{id}/verify 仅 ADMIN；GET /accounts/{id}/snapshot 供当前工作空间成员读取本地快照，GET /accounts/{id}/capabilities 返回覆盖与结果元数据，不含财务明细。状态为 NOT_VERIFIED / VERIFIED / PARTIAL / FAILED；trading_enabled=false。
- 系统：GET /health/live 仅表示进程存活；/health/ready 检查 PostgreSQL、Redis、迁移版本；/system/status 要求登录。路径均以 /api/v1 开头。
- 审计：GET /audit-logs?limit=30，仅 ADMIN；按 workspace 隔离。只记录操作元数据，不记录密码、明文密钥或请求体。
- 非生产环境提供 /api/openapi.json；直接访问 API 的 /api/docs 可查看交互文档。Nginx 的 CSP 禁止 Swagger 外部 CDN 资源，因此页面使用 JSON 链接。

聚合首页资产和 PNL 仍显示 —；账户页展示手动读取的分钱包余额和持仓，不以 0 或示例数据冒充未知余额。行情工作台 /market 已启用；告警、交易、策略仍标记后续阶段。交易开关设 true 会导致配置校验失败；没有交易或提币接口。

## 6. 验证命令

~~~powershell
uv run --directory backend ruff check .
uv run --directory backend ruff format --check .
uv run --directory backend mypy
uv run --directory backend pytest -q
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test:unit
npm --prefix frontend run build
~~~

uv 的 --directory backend 会切换工作目录并使用 backend/pyproject.toml；CI 分别进入 backend/frontend 执行相同检查。

真实依赖验收（先启动 db/cache）：

~~~powershell
uv run --directory backend python scripts/validate_foundation.py
~~~

脚本仅接受回环地址 PostgreSQL；创建带随机后缀的独立验证数据库，执行 upgrade/check/downgrade/upgrade，验证引导管理员、真实 Redis 登录限流链路、三所配置、并发密钥版本与角色权限；结束后只删除本次创建的验证数据库。应用数据库不用于测试数据。

加 --restart-data-services 会重启本项目 db/cache，检查命名卷持久化；只应在没有正在进行业务的本地开发环境执行。worker 保留基础心跳；独立 market-worker 负责公开行情，不包含私有账户同步或策略逻辑。

## 7. 安全与部署边界

- .env、数据库备份与加密密钥分开保存。丢失 Fernet key 将无法解密已存密钥；当前尚不支持自动轮换密钥，不要直接换 key/version 后继续使用旧密文。
- 新建交易所 Key 时只给读取权限，并按需要设置后端出口 IP 白名单。读取成功不代表密钥没有交易/提币权限；当前没有完整权限清单核验。仅支持明确的 GLOBAL 模式组合；DEMO 必须使用对应平台的模拟密钥，选择环境不会自动创建密钥。Binance DEMO 尚不支持。
- 登录限流依赖 Redis，缓存故障时拒绝登录，不退化成无限尝试；当前本地代理下可能共享来源桶。未配置可信代理之前不要信任任意 X-Forwarded-For。
- 公网部署必须配置 HTTPS、TRADEORBIT_APP_ENV=production、COOKIE_SECURE=true、精确 HTTPS 来源和受控反向代理。PostgreSQL 运行账号要最小权限、Redis 要网络隔离及认证；当前 Compose 的本地超级用户和无密码 Redis 不是生产方案。
- 当前版本无 MFA、密码重置、成员管理 UI、自动会话清理、密钥轮换或审计数据库防篡改；需在生产发布前单独补齐。
- 不打印 docker compose config 的完整展开结果，不输出 .env；日志/截图分享前脱敏。


## 8. 行情工作台、代理与增量升级

已有环境和管理员时跳过 init-env / bootstrap-admin；运行 docker compose up -d --build 执行新增自选与账户快照表迁移并更新服务，然后访问 /market。不要用普通 start 代替版本升级。自选按工作空间持久化，默认空列表不会自动塞入演示报价。

行情服务使用明确配置的可选 TRADEORBIT_PUBLIC_PROXY_URL，关闭 HTTPX 的系统环境代理自动继承。Windows 的系统绕过规则若包含不规范 IPv6 条目，不会使公开客户端初始化失败。未配置代理则直连官方接口。

Docker 访问本机代理应使用 host.docker.internal:实际端口；宿主机 API 开发使用对应 127.0.0.1:实际端口，在当前终端设置 TRADEORBIT_PUBLIC_PROXY_URL 覆盖 .env 即可。两者必须带 http:// 或 https://。代理应实际运行、允许容器连接；不能把示例端口当成检测结果，也不要输出代理凭据。

三所行情状态与 worker_alive 分开显示。首次目录未就绪、上游断线、目录过期或订阅超预算都会明确提示。K 线、盘口和成交标记 REST 快照，不能当作实时增量盘口。详细数据口径、权限、协议、资源上限和验收见 [E02-M1 实现文档](09-e02-public-market.md)。

M1 前端运行依赖审计 0；全量 npm audit 有 16 项中危开发工具传递依赖提示，尚未修复；M2.1 未更改依赖、未重新审计。记录在 E02-M1 文档与 DEP-01 工作项；不要把运行依赖为 0 表述成完整安全验收通过。

## 9. 手动账户快照与 M2.1 升级

已有环境先构建 API/前端，再执行增量迁移；迁移 head 为 0003_account_read_state，只新增快照表，不重建账户或加密凭据。

~~~powershell
docker compose build backend frontend
docker compose run --rm migrate
docker compose up -d backend frontend worker market-worker
docker compose ps
~~~

以管理员登录 /accounts，创建支持的连接并保存读取密钥，然后点击“验证并同步”。“查看快照”只读本地已保存数据；其他成员没有手动触发权限。凭据轮换会清理旧快照，需要重新手动验证。不要把真实密钥放进测试脚本或聊天，也不要为了验收自动遍历现有账户。

支持 Binance STANDARD/GLOBAL 的 LIVE；Bitget CLASSIC/GLOBAL 与 UTA/GLOBAL 的 LIVE/DEMO（UTA 仅 accountMode=unified）；OKX UNIFIED/GLOBAL 的 LIVE/DEMO。UNKNOWN、非 GLOBAL、Binance DEMO 和 Bitget hybrid 不支持；不自动换站、换环境。当前仅 HMAC，不支持 RSA/Ed25519。

快照按钱包分域显示：失败保留相同凭据版本的旧数据并标记 STALE；无成功记录显示 MISSING。成功空列表与失败缺失分开。超过五分钟自动标记过期；重新打开页面不会让缓存变新鲜。OKX 持仓数量保留合约张数，原生保证金率不套跨所统一风险阈值。当前没有持续私有 WS、后台自动刷新或总 NAV。

私有网络独立设置 TRADEORBIT_PRIVATE_PROXY_URL，默认留空且不继承 TRADEORBIT_PUBLIC_PROXY_URL 或系统代理。需要代理时，在本地 .env 中使用可信 http/https 代理；容器访问宿主机用 host.docker.internal，宿主机开发用 127.0.0.1。修改后重建/更新 backend；不要把代理凭据输出到日志。不得因公开行情已能连接就假定私有出口、IP 白名单和地区均通过。

同账户同步间隔至少 30 秒；交易所限流后按 Retry-After 冷却，不能连续点击绕过。认证失败、网络失败、模式不支持分别展示。真实私有账户联调仍为 NOT_RUN，需用户从页面主动触发；只读成功不能证明密钥仅有只读权限。完整口径与验收见 [M2.1 文档](10-e02-private-accounts.md)。
