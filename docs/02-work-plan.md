# TradeOrbit 开发工作计划

版本：v0.1 / 日期：2026-10-30 / 模式：需求与架构阶段，尚未开始功能实现。

## 1. 执行原则

仅设置五个顶层工作包；每包按模块交付，下面的检查项是验收清单，不是另起独立工程。先形成完整的只读闭环，再开放交易。前端可用带 schema_version 的固定回放数据并行开发，但页面必须标为演示数据。

所有工作包当前状态均为 NOT_STARTED。本次完成的是规划文档，不把编写文档算作实现完成。具体工期在 E01 环境和三所能力探测完成后评估，不虚构日期、人员或上线承诺。

~~~mermaid
flowchart LR
 E01["E01 项目基础设施"] --> E02["E02 账户资产与行情"]
 E02 --> E03["E03 告警通知与监控发布"]
 E03 --> E04["E04 可靠交易与TWAP"]
 E04 --> E05["E05 策略管理与完整发布"]
~~~

## 2. E01 项目基础设施与安全基线

优先级 P0；依赖：本套需求 / 实现设计；责任角色建议：后端、前端、运维。

### 交付范围

- 建立 frontend、backend、workers、infra、docs 的同仓目录和独立依赖清单。
- 后端入口、配置校验、结构化日志、统一错误、健康检查、OpenAPI；前端路由、布局、登录、空态和错误态。
- PostgreSQL / Redis 开发部署、SQLAlchemy / Alembic 迁移、会话认证、角色和工作空间边界。
- 账户连接配置与密钥加密接口；交易默认关闭；环境枚举、敏感日志屏蔽和审计。
- CI 的 lint / typecheck / unit / contract / build 入口；固定依赖版本，不直接使用下载目录的开发分支充当生产依赖。

主要文件：frontend/package.json、frontend/src/main.ts、frontend/src/router/index.ts、backend/pyproject.toml、backend/app/main.py、backend/app/core/config.py、backend/app/core/security.py、backend/app/api/auth.py、backend/app/models/accounts.py、backend/alembic/、infra/compose.yaml、.env.example、.gitignore、CI 配置。

需求覆盖：FR-ACC-01、02、03、06；FR-OPS-02、03、04。接口：认证、账户配置、健康和审计。详细路径见实现设计。

完成条件：TC-01 通过；空白环境能按说明启动；迁移 / 重启保留数据；角色越权测试通过；没有真实密钥进入仓库；没有启用任何实盘写接口。

## 3. E02 三所只读接入、资产与行情

优先级 P0；依赖 E01；责任角色建议：接入、后端、前端、QA。

### 交付范围

- 统一 ExchangeAdapter、CapabilityProfile、Instrument、WalletScope、Position、Order 和 EventEnvelope。
- 依次接入三所，每所先公开行情，再只读私有数据；Binance 现货 / USDⓈ-M、Bitget 经典 / UTA、OKX 交易 / 资金账户分别识别。
- 完成时间同步、限流、订阅预算、盘口重建、心跳、重连和周期性全量对账。
- 完成去重权益聚合、估值、资产快照、持仓、净值历史和资金流覆盖状态。
- 建立内部 WS 快照 + 增量协议，完成看板、自选、K 线、盘口、最近成交、资金费率、OI、爆仓来源状态。
- 为每所提供脱敏 fixture 和能力探测报告；私有数据没有凭据时只做回放测试，不能标为联调通过。

主要文件：backend/app/exchanges/base.py、backend/app/exchanges/factory.py、backend/app/exchanges/binance_adapter.py、bitget_adapter.py、okx_adapter.py、backend/app/services/valuation.py、portfolio.py、reconciliation.py、workers/market_worker.py、account_worker.py、frontend/src/stores/portfolio.ts、market.ts、frontend/src/views/OverviewView.vue、PositionsView.vue、MarketView.vue。

需求覆盖：FR-ACC-04、05；FR-AST-01 至 04；FR-MKT-01 至 06；FR-OPS-01。接口：市场 / 资产 / 持仓 / 净值 / 系统连接状态及其 WS 频道。

完成条件：TC-02 至 TC-07、TC-10、TC-15 通过；共享账户权益不重复；断线恢复不漏算成交；缺价 / 范围未覆盖可见；三所差异有配置和证据记录。

## 4. E03 告警、通知与 V0.1 发布

优先级 P0；依赖 E02；责任角色建议：后端、前端、QA、运维。

### 交付范围

- 规则 Schema、窗口计算、预热、迟到事件处理、规则版本、严重等级和告警状态机。
- 行情与系统 / 账户告警；去重、冷却、恢复、静默、规则试算与历史回看。
- 事务 outbox、通知任务、渠道适配、退避、死信和记录；Telegram / Discord / 企业微信 / Server 酱均有独立配置。
- 连接健康页、延迟指标、备份恢复说明、只读部署与故障演练。
- 用户主动发起的测试通知与后台真实告警均必须经过渠道授权开关，开发阶段使用假服务商。

主要文件：backend/app/services/alerts.py、backend/app/services/notifications.py、backend/app/models/alerts.py、outbox.py、workers/alert_worker.py、notification_worker.py、frontend/src/views/AlertsView.vue、SettingsView.vue、SystemView.vue、infra/runbooks/read-only-release.md。

需求覆盖：FR-ALT-01 至 05；FR-NTF-01 至 04；补全 FR-OPS-01 至 04。

完成条件：TC-08、09、16、17、18 通过；规则输入可追溯；发送失败不阻塞其他业务；备份实际恢复演练成功。V0.1 只读发布条件全部勾选，交易路由仍关闭。

## 5. E04 统一交易、紧急退出和 TWAP

优先级 P0；依赖 E03；责任角色建议：交易后端、前端、QA、安全审查。

### 交付范围

- 指令与交易所订单分表、幂等键、客户端订单号、风控快照、余额 / 仓位预算预留。
- REST / WS 提交能力选择、未知状态协调、订单 / 成交回补与只减仓 / 开平映射。
- 限价、市价、撤单、杠杆配置，以及普通订单 / 条件单的独立生命周期。
- 紧急退出父任务、逐账户子任务、反向组合任务和 TWAP 执行状态；不把多所操作伪装成原子事务。
- 交易界面、快捷键范围、预检、执行明细、残留仓位和失败重试入口。
- 先验证官方模拟环境；实盘只在用户另行明确授权且发布检查通过后进行最小范围验收，本计划本身不执行任何交易。

主要文件：backend/app/services/risk.py、execution.py、order_reconciler.py、emergency_exit.py、backend/app/execution/twap.py、backend/app/api/orders.py、execution_tasks.py、workers/execution_worker.py、frontend/src/views/TradeView.vue、frontend/src/components/trade/OrderForm.vue、ExecutionTaskPanel.vue。

需求覆盖：FR-TRD-01 至 07；FR-AST-05。

完成条件：TC-11 至 14、TC-19、20 通过；超时 / 重复 / 并发 / 部分成交 / 工作进程崩溃均可恢复；专项密钥与交易权限安全审查完成；V0.2 模拟环境验收与实盘启用条件分开记录。

## 6. E05 策略运行、归因与 V0.3 发布

优先级 P1；依赖 E04；责任角色建议：策略后端、前端、QA、运维。

### 交付范围

- 插件注册、参数 JSON Schema、版本、账号权限、预算和独立进程运行器；策略仅产生 Intent，不能绕过统一交易风控。
- 状态机、参数变更审计、暂停 / 撤单 / 平仓控制、实例日志、心跳、崩溃恢复和参数版本恢复。
- 同标的持仓所有权规则、策略成交账本、费用与收益归因；起步按账户 / 标的独占，复杂净额分摊另行扩展。
- 网格 / 趋势基准插件、历史回放、模拟成交模型说明；TWAP 继续作为执行算法复用。
- 完整链路压力、恢复、部署回滚和用户验收；回测能力按分期建立，不承诺首版具备研究平台的全部能力。

主要文件：backend/app/strategies/contracts.py、registry.py、runner.py、backend/app/services/strategy_control.py、attribution.py、workers/strategy_worker.py、frontend/src/views/StrategiesView.vue、frontend/src/components/strategy/LogStream.vue、tests/replay/、infra/runbooks/strategy-release.md。

需求覆盖：FR-STR-01 至 05；补全 FR-AST-05 和所有端到端验收。

完成条件：TC-21、22、23 通过；旧实例不再发送新指令后才交接控制权；策略运行状态、订单和持仓一致；无未解决的交易安全阻断项。

## 7. 发布门槛与范围变更

| 检查点 | 必须具备 | 不满足时处理 |
|---|---|---|
| G1 基础可运行 | 迁移、认证、配置和密钥加密 | 留在本地开发 |
| G2 只读可发布 | 三所覆盖报告、对账、过期标识和告警 | 相关账户 / 能力标为未通过，不开放交易 |
| G3 交易可验收 | 模拟环境故障测试、幂等、只减仓、未知状态、安全审查 | 保持 trading_enabled=false |
| G4 策略可发布 | 隔离、预算、重启、归因和退出流程 | 策略只运行回放 / 模拟 |

新增交易所或账户模式，要补 CapabilityProfile、签名 / 数据 fixture、接入文档、契约测试和只读 / 交易验收，不能只在下拉框加名称。性能扩容先测瓶颈，再决定分区、消息中间件和时序存储，不预先引入复杂微服务。

## 8. 项目推进记录模板

每次交付记录：工作包、关联需求、修改文件、测试证据、接入环境、阻断项、回滚方式和剩余风险。测试结果只填实际执行证据；没有凭据、网络或环境时写 NOT_RUN，不能用“源码存在”替代通过。
