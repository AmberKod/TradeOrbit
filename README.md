# TradeOrbit · 交易星轨

面向 Binance、Bitget、OKX 的多交易所资产、行情与交易工作台。前后端分离，同仓维护。

## 当前进度

2026-10-30：E01 基础工程已完成本地验收；前后端、数据库、缓存与 Worker 容器已启动并通过健康检查。E02 三所只读接入尚未开始。当前可用：

- 登录、会话恢复、退出；管理员 / 交易员 / 观察者与工作空间隔离。
- 账户连接创建、查询、重命名 API、归档；明确区分 DEMO / LIVE 与账户模式。
- 交易所 API 凭据加密保存且不回传明文；管理员权限、CSRF、来源校验、登录限流与审计。
- 中文响应式前端：资产空态、账户配置、系统状态、操作审计。
- PostgreSQL / Redis、Alembic、独立心跳 Worker、Docker Compose 与 CI。

账户配置统一显示“未验证”。不连接真实交易所，不显示虚构余额，不执行订单或外部通知；交易开关保持锁定。

## 快速启动

需要 Docker、Python 3.12、uv、Node.js 22.12+。在项目根目录运行：

~~~powershell
uv sync --directory backend --extra dev --frozen
uv run --directory backend python -m app.cli init-env
docker compose up -d --build
docker compose exec backend python -m app.cli bootstrap-admin --email your-email@example.com
~~~

已有 .env 时跳过 init-env；它不会覆盖已有密钥。管理员密码由你交互式设置，没有默认密码。浏览器访问 http://localhost:18080 。本地所有服务端口仅绑定 127.0.0.1。

详细安装、宿主机开发、角色创建、验证和安全边界见 [运行手册](docs/07-local-development.md)。

## 验证与文档

- 后端：21 项测试、Ruff、mypy、依赖锁检查通过。
- 前端：8 项测试、lint、类型检查与生产构建通过；npm audit 本轮 0 漏洞。
- 真实 PostgreSQL / Redis：迁移升级/回退/模型一致性、并发凭据更新与重启持久化通过；验证数据库已清理。
- 容器部署、同源代理与健康检查通过；桌面/390px 窄屏登录页无横向溢出及脚本异常。
- [E01 验收记录](docs/08-e01-acceptance-report.md)
- [文档导航](docs/README.md) · [功能需求](docs/01-product-requirements.md) · [工作计划](docs/02-work-plan.md)
- [实现设计](docs/03-implementation-design.md) · [统一接入规范](docs/04-exchange-integration.md)
- [Binance](docs/exchanges/binance.md) · [Bitget](docs/exchanges/bitget.md) · [OKX](docs/exchanges/okx.md)

交付顺序：E01 基础工程 → E02 只读账户与行情 → E03 告警与通知 → E04 可靠交易与 TWAP → E05 隔离策略。实盘交易必须另行明确授权并完成专项验收。
