# TradeOrbit · 交易星轨

面向 Binance、Bitget、OKX 的多交易所资产、行情与交易工作台。前后端分离，同仓维护。

## 当前进度

2026-10-31：E01 基础工程保持可用；E02-M1 公开行情与 E02-M2.1 私有账户手动只读同步完成（工程版本 0.2.0）。E02 总体仍进行中，持续私有流、周期对账和聚合 NAV 留待后续。当前可用：

- 登录、会话恢复、退出；管理员 / 交易员 / 观察者与工作空间隔离。
- 账户连接创建、查询、重命名 API、归档；明确区分 DEMO / LIVE 与账户模式。
- 交易所 API 凭据加密保存且不回传明文；管理员权限、CSRF、来源校验、登录限流与审计。
- 中文响应式前端：资产空态、账户配置、系统状态、操作审计。
- PostgreSQL / Redis、Alembic、独立心跳 Worker、Docker Compose 与 CI。
- 三所 USDT 现货 / 永续公开 WebSocket 行情、持久化自选、断线与过期状态。
- 行情详情：1 分钟 K 线、买卖各 5 档、最近 20 笔成交的 REST 快照。
- 管理员手动验证并同步账户；分钱包余额、持仓、失败和过期快照展示，密钥轮换后清理旧数据。

公开行情连接真实公共市场接口，不需要账户密钥。私有请求只由管理员在账户页点击“验证并同步”触发；支持 Binance STANDARD/GLOBAL 的 LIVE、Bitget CLASSIC/UTA 与 OKX UNIFIED/GLOBAL 的 LIVE/DEMO。保存密钥或打开页面不会自动同步；未验证、范围缺失和失败保留的旧数据均明确标记。真实私有账户联调尚未执行，支持范围与限制见下方 M2.1 文档；交易开关保持锁定。

## 快速启动

需要 Docker、Python 3.12、uv、Node.js 22.12+。在项目根目录运行：

~~~powershell
uv sync --directory backend --extra dev --frozen
uv run --directory backend python -m app.cli init-env
docker compose up -d --build
docker compose exec backend python -m app.cli bootstrap-admin --email your-email@example.com
~~~

已有 .env 时跳过 init-env；它不会覆盖已有密钥。管理员密码由你交互式设置，没有默认密码。浏览器访问 http://localhost:18080 ，行情入口为 /market。本地所有服务端口仅绑定 127.0.0.1。

详细安装、宿主机开发、角色创建、验证和安全边界见 [运行手册](docs/07-local-development.md)。

## 验证与文档

- 后端：87 项测试、Ruff 检查与格式检查、mypy（40 个源文件）通过；依赖锁检查结果见 M1 历史记录。
- 前端：20 项测试、lint、类型检查与生产构建通过。M1 运行依赖审计为 0；全量审计 16 项中危开发工具依赖提示仍待升级，本轮未重新审计。
- 真实 PostgreSQL / Redis：迁移升级/回退/模型一致性、并发凭据更新与重启持久化通过；验证数据库已清理。
- 六组真实公开 REST/WS、容器到浏览器推送、真实自选增删与刷新持久化通过；桌面/390px 行情页无文档横向溢出及脚本异常。
- [E01 验收记录](docs/08-e01-acceptance-report.md)
- [E02-M1 功能、实现与验收](docs/09-e02-public-market.md)
- [E02-M2.1 私有账户只读接入与验收](docs/10-e02-private-accounts.md)
- [文档导航](docs/README.md) · [功能需求](docs/01-product-requirements.md) · [工作计划](docs/02-work-plan.md)
- [实现设计](docs/03-implementation-design.md) · [统一接入规范](docs/04-exchange-integration.md)
- [Binance](docs/exchanges/binance.md) · [Bitget](docs/exchanges/bitget.md) · [OKX](docs/exchanges/okx.md)

交付顺序：E01 基础工程 → E02 只读账户与行情 → E03 告警与通知 → E04 可靠交易与 TWAP → E05 隔离策略。实盘交易必须另行明确授权并完成专项验收。
