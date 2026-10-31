# TradeOrbit 功能实现设计

版本：v0.2 / 更新：2026-10-31 / 属性：全量技术规格；E01 以 [验收记录](08-e01-acceptance-report.md) 为准，E02 已完成 [M1 公开行情](09-e02-public-market.md) 与 [M2.1 手动账户快照](10-e02-private-accounts.md)，持续私有同步与聚合 NAV 待实现，E03–E05 仍为设计；需求以 PRD 的 FR 编号为准。

## 1. 实现方式与模块边界

采用模块化后端和独立 worker，前后端独立构建，由反向代理提供同源入口。前端不直连私有交易所接口。当前 M1/M2.1 使用受控原生 REST/WS 适配，CCXT 只作源码与字段核对参考，未引入为运行依赖；后续如引入 SDK 仍不作为业务数据库或资产账本。Hummingbot / Freqtrade / FreqUI 是设计参考，源码许可证见来源登记表。

~~~mermaid
flowchart TB
 B[浏览器 Vue3] --> G[反向代理 HTTPS]
 G --> A[FastAPI HTTP + WebSocket]
 A --> D[(PostgreSQL)]
 A --> R[(Redis 缓存/广播)]
 M[行情Worker] --> X[ExchangeAdapter]
 C[账户同步Worker] --> X
 E[交易执行Worker] --> X
 X --> EX[Binance / Bitget / OKX]
 M --> R
 C --> D
 E --> D
 D --> O[事务Outbox分发]
 O --> N[告警/通知Worker]
 O --> A
 S[隔离策略Worker] --> I[Intent + 风控入口]
 I --> D
~~~

职责：API 负责认证、权限、请求校验、命令落盘和查询；行情 worker 负责公开订阅与行情状态；账户 worker 负责私有增量 / 全量对账；执行 worker 是交易所写操作的唯一业务入口；策略只能提交 Intent；通知和日志流不阻塞任何交易关键路径。

核心数据隔离键为 workspace_id + exchange + environment + connection_id + wallet_scope_id + instrument_id。策略归因单独建账，不能把一个净持仓无条件归为最后一个下单策略。

## 2. 目录与文件职责

~~~text
frontend/
  src/api/{client,portfolio,markets,orders,alerts,strategies}.ts
  src/stores/{session,accounts,portfolio,market,execution,alerts}.ts
  src/realtime/{client,protocol,subscriptions}.ts
  src/views/{Overview,Positions,Market,Trade,Strategies,Alerts,Settings,System}View.vue
  src/components/{charts,market,trade,strategy,common}/
  src/types/{domain,api,events}.ts
backend/
  app/main.py
  app/core/{config,security,errors,logging,clock}.py
  app/api/{auth,accounts,portfolio,markets,orders,execution_tasks,alerts,strategies,ws}.py
  app/models/{accounts,portfolio,market,orders,strategies,alerts,outbox,audit}.py
  app/schemas/{accounts,portfolio,market,orders,events}.py
  app/exchanges/{base,factory,capabilities,binance_adapter,bitget_adapter,okx_adapter}.py
  app/services/{valuation,portfolio,reconciliation,risk,execution,emergency_exit,alerts,notifications}.py
  app/execution/{state_machine,twap}.py
  app/strategies/{contracts,registry,runner}.py
  app/realtime/{gateway,snapshot,replay}.py
  alembic/versions/
workers/{market_worker,account_worker,execution_worker,alert_worker,notification_worker,strategy_worker}.py
infra/{compose.yaml,proxy.conf,runbooks/}
tests/{unit,contracts,replay,integration,e2e,load}/
~~~

workers 是入口与编排，复用 backend 中的领域服务；不复制交易逻辑。起步单机多进程，扩容时按账户写入所有权和订阅分片，不能直接启动两个相同执行实例。

## 3. 领域对象与适配接口

~~~mermaid
classDiagram
 class AccountConnection {
   UUID id
   string exchange
   string environment
   string account_mode
   probe_capabilities()
 }
 class WalletScope {
   UUID id
   string equity_scope_key
   string valuation_currency
 }
 class Instrument {
   string exchange_symbol
   string market_type
   string settle
   Decimal contract_size
 }
 class ExchangeAdapter {
   load_markets()
   fetch_snapshot()
   watch_events()
   submit_order()
   reconcile_order()
 }
 class OrderCommand {
   UUID id
   string idempotency_key
   string status
 }
 class ExchangeOrder {
   string client_order_id
   string exchange_order_id
   Decimal filled
 }
 class RiskService {
   precheck()
   reserve_budget()
 }
 AccountConnection "1" --> "1..*" WalletScope
 ExchangeAdapter --> AccountConnection
 ExchangeAdapter --> Instrument
 RiskService --> OrderCommand
 OrderCommand "1" --> "0..*" ExchangeOrder
~~~

Adapter 协议详见统一接入规范。服务层只能使用标准对象和能力描述；需要的原始字段放在带来源版本的扩展结构中，不让交易所字段散落在页面。

## 4. 数据库设计

所有业务表带 id、workspace_id、created_at、updated_at；所有 UTC 时间用 timestamptz；金额、价格、数量用 NUMERIC(38,18)，接口用十进制字符串。选择此精度后 E01 必须用真实市场精度样本验证边界，不能静默截断。JSONB 只存扩展信息，不代替关键字段和约束。

| 表 | 核心字段 | 唯一键 / 约束 / 作用 |
|---|---|---|
| users / memberships | user_id、workspace_id、role | 用户工作空间角色唯一 |
| sessions | user_id、token_hash、expires_at、revoked_at | 仅存会话摘要，支持失效 |
| account_connections | exchange、environment、account_mode、credential_ref、status | 同账户身份可关联多个域，不能靠昵称去重 |
| encrypted_credentials | ciphertext、nonce、key_version、algorithm | 主密钥与数据库分离，禁止明文回读 |
| wallet_scopes | connection_id、external_scope_id、equity_scope_key、scope_type | 资产计量去重键包含环境；共享钱包域唯一 |
| capability_profiles | connection_id、market_type、api_version、capabilities、verified_at | UNKNOWN / SUPPORTED / UNSUPPORTED / VERIFIED 分开 |
| instruments | exchange、exchange_symbol、market_type、base、quote、settle、contract_size、tick_size、lot_size、min_notional、status、revision | 交易所 + 原生标的 + 产品类型唯一 |
| balance_snapshots | wallet_scope_id、currency、total、available、debt、equity、source_time、revision | 不跨钱包简单相加；保留权益来源 |
| positions | account_id、instrument_id、position_side、quantity、contracts、entry_price、mark_price、liquidation_price、unrealized_pnl、margin_mode、native_risk | 账户 + 标的 + 多空边唯一，零仓归档受事件类型约束 |
| portfolio_snapshots | scope_set_id、nav、currency、coverage、as_of、source_watermarks | 不完整估值不可伪装完整 NAV |
| cashflows | source_id、direction、asset、amount、flow_time、transfer_pair_id、scope_boundary | 去重；内部 / 外部由统计边界判断 |
| order_commands | account_id、idempotency_key、payload_hash、intent、status、risk_snapshot、reservation_id | 账户 + 幂等键唯一；相同键不同请求返回冲突 |
| exchange_orders | command_id、client_order_id、exchange_order_id、kind、status、filled、remaining、last_exchange_time | client_order_id 唯一域按所实现；普通单和条件单分别标记 |
| fills | account_id、instrument_id、trade_id、order_id、qty、price、fee、fee_currency、fill_time | 按交易所 trade_id 实际作用域建唯一键，不跨标的误去重 |
| risk_reservations | command_id、amount、scope、status、expires_at | 未知订单不能仅因超时就释放预算 |
| execution_tasks | kind、scope、state、progress、remaining_exposure、parent_id | 一个父任务可有逐账户 / 标的子任务 |
| strategy_instances | plugin、version、config_version、account_scope、state、budget、ownership | 一账户 / 标的初期使用独占所有权 |
| strategy_ledger | strategy_id、fill_id、allocation、funding、fee | 归因分配可回放，不重写交易所事实 |
| alert_rules / alert_events | rule_version、scope、condition、input_watermarks、dedup_key、state | 告警依据不可变，规则修改生成新版本 |
| notification_jobs / deliveries | event_id、channel_id、state、attempt、next_retry_at、provider_ref | 事件 + 渠道 + 模板版本去重 |
| outbox_events / consumer_offsets | event_id、aggregate_id、sequence、payload、published_at | 与业务记录同事务提交；消费幂等 |
| audit_logs | actor、action、scope、request_id、redacted_before_after、outcome | 追加式记录，无 Secret / 签名 / 完整会话令牌 |

市场成交与盘口采用按需保存策略：K 线与必要事件持久化，深度默认缓存及故障回放采样；不默认长期存所有市场全量 tick。原始报文先脱敏，设留存与访问控制。重要订单报文和脱敏异常帧可用于对账。

## 5. HTTP API 契约

统一前缀 /api/v1。成功使用 {data, meta:{request_id,as_of,coverage,schema_version}}；失败使用 {error:{code,message,retryable,details},meta:{request_id}}。列表支持 limit + cursor；业务 ID 为 UUID；金额为字符串；枚举使用固定英文值。任何可写资源都必须检查角色、工作空间、环境和账户授权。

| 分组 | 路由与语义 |
|---|---|
| 会话 | POST /auth/login；POST /auth/logout；GET /auth/session；POST /auth/refresh（若采用有期限会话续期） |
| 账户 | GET/POST /accounts；GET/PATCH/DELETE /accounts/{id}；POST /accounts/{id}/credentials；POST /accounts/{id}/probe；GET /accounts/{id}/capabilities；GET /accounts/{id}/sync-status |
| 账户恢复 | POST /accounts/{id}/reconcile；GET /accounts/{id}/wallet-scopes；GET /accounts/{id}/cashflows |
| 资产 | GET /portfolio/summary；GET /portfolio/history；GET /positions；GET /balances；GET /pnl/summary；GET /pnl/attribution |
| 市场 | GET /instruments；GET /markets/tickers；GET /markets/{instrument_id}/candles；/orderbook；/trades；/funding；/open-interest；/liquidations |
| 自选 | GET/POST /watchlists；PATCH/DELETE /watchlists/{id}；PUT /watchlists/{id}/items |
| 交易 | POST /orders/precheck；POST /orders；GET /orders；GET /orders/{id}；POST /orders/{id}/cancel；GET /fills |
| 模式设置 | POST /accounts/{id}/trading-settings/precheck；POST /accounts/{id}/trading-settings；禁止下单时静默修改账户级持仓模式 |
| 执行任务 | POST /execution-tasks（EMERGENCY_EXIT / REVERSE / TWAP）；GET /execution-tasks/{id}；POST /execution-tasks/{id}/cancel；GET /execution-tasks/{id}/events |
| 风控 | GET /risk/limits；PUT /risk/limits/{scope_id}；GET /risk/events；POST /risk/kill-switch；POST /risk/resume（完成对账后） |
| 告警 | GET/POST /alert-rules；PATCH/DELETE /alert-rules/{id}；POST /alert-rules/{id}/test；GET /alert-events；POST /alert-events/{id}/ack；POST /alert-events/{id}/silence |
| 通知 | GET/POST /notification-channels；PATCH/DELETE /notification-channels/{id}；POST /notification-channels/{id}/test；GET /notification-deliveries；POST /notification-deliveries/{id}/retry |
| 策略 | GET /strategy-plugins；GET/POST /strategy-instances；PATCH /strategy-instances/{id}/config；POST /strategy-instances/{id}/actions；GET /strategy-instances/{id}/logs；GET /strategy-instances/{id}/performance |
| 运维 | GET /health/live；GET /health/ready；GET /system/connections；GET /system/metrics-summary；GET /audit-logs |
| 实时 | GET /ws 升级；会话鉴权 + Origin 校验 + 逐频道授权；不把长期访问令牌放在 URL |

DELETE /accounts/{id} 是停用 / 归档，不级联删除订单与审计。危险写操作使用 Idempotency-Key；相同键与相同 payload 返回原结果，不同 payload 返回 409。交易提交返回 202 + command_id，表示持久化受理而非交易所成交。

错误码至少含：UNAUTHENTICATED、FORBIDDEN、CAPABILITY_UNAVAILABLE、ACCOUNT_NOT_READY、MARKET_DATA_STALE、INVALID_PRECISION、MIN_NOTIONAL、RISK_LIMIT、IDEMPOTENCY_CONFLICT、ORDER_STATE_UNKNOWN、RATE_LIMITED、RECONCILIATION_REQUIRED。不能把全部交易所失败统一包装成“网络错误”。

### 普通委托示例

~~~json
{
  "account_id": "uuid",
  "instrument_id": "uuid",
  "environment": "DEMO",
  "type": "LIMIT",
  "side": "BUY",
  "action": "OPEN",
  "position_side": "LONG",
  "quantity": {"value": "0.001", "unit": "BASE"},
  "price": "50000.00",
  "time_in_force": "GTC",
  "reduce_only": false,
  "source": {"kind": "MANUAL", "strategy_instance_id": null},
  "expected_instrument_revision": 1
}
~~~

示例价格和数量仅是协议样例，不是行情、下单建议或可执行测试单。数量单位 BASE / CONTRACTS / QUOTE_NOTIONAL 显式指定，接口预检返回交易所最终数量、精度调整、名义金额和费用估算。不能只填一个无单位 amount。用户提交与预检不同或市场规格变化时重新校验。

## 6. 内部实时协议

频道：market.ticker、market.orderbook、market.trades、market.candle、market.funding、market.oi、market.liquidation、account.balance、account.position、account.order、portfolio.nav、execution.task、alert.event、strategy.state、strategy.log、system.health。

~~~json
{
  "schema_version": 1,
  "event_id": "uuid",
  "type": "account.position.updated",
  "channel": "account.position",
  "stream_epoch": "uuid",
  "seq": 1024,
  "exchange_time": "2026-10-30T00:00:00Z",
  "received_at": "2026-10-30T00:00:00.120Z",
  "published_at": "2026-10-30T00:00:00.140Z",
  "account_id": "uuid",
  "instrument_id": "uuid",
  "quality": {"state": "LIVE", "coverage": "COMPLETE"},
  "payload": {}
}
~~~

客户端发送 subscribe / unsubscribe / ping，订阅携带频道、scope 和 last_seq。服务端逐频道授权；序号以频道 / scope / epoch 为作用域，不能误认成跨所全局序号。重连后可重放的关键事件从持久化事件取回；超出留存或 epoch 改变时返回 resync_required。

初始化流程：服务端先建立增量缓冲，读出带 revision 的快照并发送 snapshot，再发送高于该 revision 的增量。若外部源没有可比较序号，账户同步服务使用重叠拉取、去重和二次对账建立自己的版本；不能凭接收先后证明没有缺口。

行情可合并为最新值，浏览器按可配置的 100–250ms 周期绘制；订单、成交和任务状态不可静默丢弃。缓冲溢出时中止频道并要求重同步。Redis Pub/Sub 仅用于允许丢弃的行情提示；关键事实持久化在 PostgreSQL + outbox，达到至少一次分发，消费者按 event_id / aggregate sequence 幂等处理。

## 7. 订单、风控与恢复

~~~mermaid
sequenceDiagram
 participant UI as 前端
 participant API as API
 participant DB as PostgreSQL
 participant EXE as 执行Worker
 participant EX as 交易所
 UI->>API: POST orders + Idempotency-Key
 API->>DB: 记录命令与请求摘要
 API-->>UI: 202 command_id
 EXE->>DB: 获得账户写入权并检查状态
 EXE->>EXE: 最新风控与额度预留
 EXE->>EX: 提交带client_order_id的委托
 alt 明确受理
 EX-->>EXE: 交易所订单号
 EXE->>DB: 保存受理，等待订单/成交事件
 else 响应丢失或超时
 EXE->>DB: UNKNOWN，保留预算
 EXE->>EX: 按客户端订单号查询并回补成交
 end
 DB-->>API: outbox订单状态
 API-->>UI: WebSocket事实更新
~~~

命令状态：RECEIVED → VALIDATING → RISK_REJECTED 或 QUEUED → SUBMITTING → ACKNOWLEDGED / REJECTED / UNKNOWN。命令受理状态与订单成交状态不同。订单状态：PENDING_NEW、OPEN、PARTIALLY_FILLED、FILLED、CANCEL_PENDING、CANCELED、EXPIRED、REJECTED、UNKNOWN；撤单期间仍可成交，先取消再看到成交不算矛盾，累计成交不得回退。

client_order_id 在发送前持久化。建议使用短于各所共同限制的字母数字编码，但长度 / 唯一域必须由连接器验证。相同请求幂等键冲突由数据库唯一约束处理，不只依靠 Redis 锁。条件单和触发后生成的普通单保留 parent / child 关联，触发受理不等于平仓成交。

写前校验：权限和环境 → 账户同步状态 → 市场交易状态及规格版本 → 金额与价格精度 → 持仓模式 / 开平语义 → 可用预算 → 单笔 / 总名义金额 → 杠杆与日内亏损 → 数据有效性 → 重复 / 冲突操作。账户级限制优先于策略预算；并发请求预留额度，避免每笔独立检查都通过却合计超限。

超时不自动换 client_order_id 重下。按已知客户端号 / 交易所号、挂单、历史订单与成交综合核对；“查询暂未找到”不是未下单证明。无法判定时保持 UNKNOWN、保留预算、阻止冲突开仓，允许管理员基于证据恢复。

账户写入使用单一执行所有者、数据库锁 / 租约和本地 fencing 校验。接管前确认旧 worker 已终止或无法再发送；仅数据库租约过期不能撤回已经发到交易所的请求。存在不确定请求时先对账，不把命令自动交给新 worker 再发一遍。

紧急退出不是跨所事务：先冻结范围内新增指令、停策略新增；撤普通开仓单及相关条件单并查询结果；获取最新仓位；按模式使用经过验证的关闭语义；对成交、余仓、残留条件单持续核对。断开私有流时，可用已验证 REST 拉取最新仓位走退出专用降级路径；REST 也不可用时停止盲目发送并告警。完成条件是范围内余仓和危险挂单都符合目标，不是收到平仓 ACK。

反向任务只有确认旧仓已平 / 明确剩余量后才进入下一阶段；开反向仓仍需所有正常新开仓风控。不得通过简单两倍市价单替代整个流程。

## 8. 资产、行情与告警实现

估值服务按 equity_scope_key 去重，读取同一估值水位附近的账户快照，建立有效价格路径。无价格、源数据过期、借贷未覆盖或部分账户不可用时返回 PARTIAL / UNPRICED，保留上一有效值并标旧；不拿 0 补齐。USDT、USDC、BTC 等换算均有来源和时间，稳定币不永久硬编码 1:1。

PNL / 风险字段保留 native_value、单位、危险方向和账户模式。线性合约可计算核验值，但界面展示与交易所标记价格口径对齐。不同币种手续费分币存储，按指定时点汇率折算；资金费与充提不混类。

行情订阅由引用计数和预算管理；ticker 用轻量通道，深度只对选中标的订阅。快照 + 增量合成盘口遵循各所序列规则；检测缺口后立即 INVALID → 重新快照 → LIVE。迟到或重复成交按原始成交 ID 与事件时间去重。

规则计算采用事件时间窗口，记录 watermark、允许迟到策略和基线。基础定义：price_change = price_now / price_at_window_start - 1；volume_ratio = 当前滚动窗口quote成交量 / 不含当前窗口的历史窗口均量。基线为零、样本不足、源不完整时为 WARMING_UP / INSUFFICIENT_DATA，不触发正常阈值。

告警事件含 rule_version、observed_value、threshold、window、source_event_ids / watermarks。状态 NORMAL → FIRING → ACKNOWLEDGED / SILENCED → RESOLVED；确认 / 静默不代表风险消除。持仓风险和数据健康规则独立于市场波动规则。

## 9. TWAP、策略与通知

TWAP 将预算、期限、间隔、限价保护和交易规格转换为可持久化的子单计划；按完成子单与实时剩余预算决定下一单，不能每个定时器都再次提交总数量。末笔处理精度余数，不足最小数量则结束为 PARTIAL 并列出余量；不能为了凑最小单突破总预算。挂单重报前处理撤单与期间成交；进程重启先核对历史子单，不从第一单重新执行。

策略插件只暴露元信息、参数 Schema、on_market_event / on_timer / on_fill 和 Intent 输出。插件不持有交易所密钥；由策略运行器提供受限数据 / 命令客户端。状态 STOPPED → STARTING → RUNNING → PAUSED / STOPPING → STOPPED，异常为 ERROR / RECOVERING。热更新仅允许插件声明的参数，其他变更需停止、对账、重启并记录配置版本。

起步同一账户 / 标的由一个交易控制者独占；手动接管必须解除策略控制并对账。模拟、回放和实盘隔离数据与凭据；回测与模拟不等价于可成交的实盘结果。

通知使用 outbox → job → 渠道适配器，状态 PENDING / SENDING / PROVIDER_ACCEPTED / DELIVERED / RETRY_WAIT / UNKNOWN / DEAD。服务商明确回执才写 DELIVERED；无幂等 API 时不能承诺外部 exactly-once。远端受理但响应丢失需避免高频重试并保留不确定状态。渠道域名和重定向受控，Webhook 设置应防 SSRF。

## 10. 安全、部署与运维

登录采用服务端会话 + HttpOnly / Secure / SameSite cookie；写请求做 CSRF 校验，WS 校验 Origin 与会话并逐频道鉴权。若部署跨域，必须显式 CORS allowlist，不能 credentials + 通配符。公开只读行情也经后端缓存与访问限制，避免浏览器连接数无界增长。

交易所 Secret / Passphrase / 私钥使用带版本的认证加密保存；主密钥由环境或密钥服务提供，与数据库备份分离。API 密钥、签名、Cookie、WS URL 查询令牌全部脱敏。管理员轮换密钥后旧连接退出，待重建和对账完成再允许交易。对鉴权、外部输入、Webhooks 和交易权限安排专项安全审查。

建议配置项：APP_ENV、DATABASE_URL、REDIS_URL、ENCRYPTION_KEY_REF、SESSION_SECRET_REF、TRADING_ENABLED=false、ALLOWED_ORIGINS、MARKET_STALE_POLICY、ACCOUNT_RECONCILE_INTERVAL、RETENTION_POLICY、EXCHANGE_REGION_PROFILES。示例配置只放占位符。

开发可在 Windows 运行前后端，部署优先采用 Linux 容器；Cython 或其他原生依赖需独立验证，不默认把 Hummingbot 整体装入 API。反向代理对外仅开放 HTTPS；数据库 / Redis 放内部网络。

指标：外部事件至接收、接收至发布、浏览器展示延迟分别测量；采集 WS 心跳、重连、sequence gap、REST 权重、429、对账差异、未知订单、outbox积压、通知重试和策略心跳。业务 readiness 不能只检查进程存活。

恢复：先停新增交易 → 恢复数据库与配置 → 恢复密钥 → 只读连接与全量对账 → 核对未知命令和剩余敞口 → 人工解除交易锁。发布回滚须检查数据库兼容和未完成执行任务；不能简单重启旧版本并重新执行所有队列。

## 11. 交付验证

本文件定义的对象、路径与协议均需实现后生成 OpenAPI / JSON Schema 并做前后端契约校验。数据库迁移、状态机回放、权限隔离、重复 / 乱序事件和故障恢复是必测项；具体清单见测试与验收文档。外部 URL、模式和字段的真实可用性以三所接入记录为准。
