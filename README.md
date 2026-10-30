# TradeOrbit
A real-time multi-exchange trading platform for Binance, OKX, and Bitget, with portfolio monitoring, market alerts, and strategy management.

TradeOrbit（交易星轨）是面向 Binance、Bitget、OKX 的资产、持仓、行情、交易与策略工作台。

## 当前状态

2026-10-30：需求、开发工作计划、实现设计和三所接入说明已形成第一版文档。应用功能尚未实现；文档描述的是目标行为与验收标准。

## 文档

- [文档导航与基线](docs/README.md)
- [功能需求](docs/01-product-requirements.md)
- [开发工作计划](docs/02-work-plan.md)
- [功能实现设计](docs/03-implementation-design.md)
- [交易所统一接入规范](docs/04-exchange-integration.md)
- [Binance 接入](docs/exchanges/binance.md)
- [Bitget 接入](docs/exchanges/bitget.md)
- [OKX 接入](docs/exchanges/okx.md)
- [测试与验收](docs/05-test-acceptance.md)
- [来源、版本与待验证事项](docs/06-source-register.md)

## 交付顺序

V0.1 只读资产 / 行情 / 告警 → V0.2 手动交易 / 可靠执行 / TWAP → V0.3 隔离策略运行。

建议基础栈：Vue 3 + TypeScript + Vite + Pinia；Python + FastAPI + asyncio；PostgreSQL + Redis；CCXT 与必要的原生适配。

实际支持的账户、市场、环境与高级订单类型，以后续能力探测和联调验收为准。
