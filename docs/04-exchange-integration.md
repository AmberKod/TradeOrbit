# TradeOrbit 交易所统一接入规范

版本 v0.1 / 核对日期 2026-10-30 / 适用需求 FR-ACC-02 至 06、FR-AST、FR-MKT、FR-TRD。

## 1. 接入路线与代码依据

使用 CCXT / CCXT Pro 的 Python 接口完成公共 REST、公开行情与私有账户流，并在 TradeOrbit 中封装标准适配器。缺失能力使用明确版本的原生接口补充。依赖 pin 到测试过的发布版本；本地 CCXT 4.5.91 是源码核对快照，不代表其所有方法已完成账户联调。

源码权威入口为 E:/github_repo/ccxt/ts/src/{exchange}.ts 和 ts/src/pro/{exchange}.ts；Python 交易所文件为生成代码。若需要上游修复，遵守该库 AGENTS.md / CLAUDE.md，在 TypeScript 源文件修复并运行相应测试。TradeOrbit 的业务适配代码保留在自己的仓库。

| 能力 | Binance | Bitget | OKX | TradeOrbit 处理 |
|---|---|---|---|---|
| 现货 / USDT 永续 REST | 有实现 | 有实现，分经典 / UTA | 有实现，账户模式影响参数 | 实际权限 / 产品逐项探测 |
| ticker / 盘口 / 成交 WS | 有实现 | 有实现 | 有实现 | 使用选定频道，检测快照和序列 |
| 余额 / 持仓 / 订单 WS | 有实现，现货与合约路径不同 | 有实现，v2 / v3 和字段不同 | 有实现，交易账户与资金账户分离 | REST 初始化和周期对账仍必需 |
| CCXT createOrderWs | 本地标为 true，产品支持另核对 | 本地标为 false | 本地标为 true | 先支持已验证 REST，WS 不作为功能前提 |
| 爆仓 WS | 本地有 watchLiquidations | 本地 pro 未见对应实现，需原生扩展评估 | 本地有相关实现 | 显示覆盖 / 采样，不能声称全量 |
| 模拟环境 | Spot Testnet / Futures demo 分开 | Demo Trading 独立配置 | Demo Key + 模拟标识 / WS 域名 | 按环境配置，禁止自动退回实盘 |

表中“有实现”仅是本地源码证据。CapabilityProfile 记录 SDK 实现、官方说明、账号许可、环境和最近验证结果；四者都满足才向 UI 暴露为可交易。

## 2. 标准对象与适配器协议

Instrument 至少包含 exchange、native_symbol、market_type、base、quote、settle、linear、contract_size、amount_unit、price_tick、amount_step、min_amount、min_notional、trade_status、revision。一个内部 instrument_id 对应一个原生市场；跨所比较用单独映射关系，不复用交易主键。

WalletSnapshot 保留 equity_scope_key、原生总权益、可用权益、币种明细、负债、原始风险口径、source_time、coverage 和原始摘要。Position 保留 side、base_quantity、contracts、contract_size、margin_mode、leverage、entry / mark / liquidation price、unrealized_pnl、native_risk。Order / Fill 同时保留内部 ID 和交易所 ID。

~~~python
class ExchangeAdapter(Protocol):
    async def probe(self) -> CapabilityProfile: ...
    async def load_instruments(self) -> list[Instrument]: ...
    async def fetch_wallet_snapshot(self) -> WalletSnapshot: ...
    async def fetch_positions(self) -> list[Position]: ...
    async def fetch_open_orders(self, scope: OrderScope) -> list[Order]: ...
    async def fetch_order(self, ref: OrderReference) -> OrderLookupResult: ...
    async def fetch_fills(self, cursor: FillCursor) -> FillPage: ...
    def watch_public(self, request: Subscription) -> AsyncIterator[Event]: ...
    def watch_private(self) -> AsyncIterator[Event]: ...
    async def submit_order(self, request: NormalizedOrder) -> SubmitResult: ...
    async def cancel_order(self, ref: OrderReference) -> CancelResult: ...
    async def close(self) -> None: ...
~~~

协议是设计示意，不是已可执行 SDK。fetch_order 不能用 None 同时表示“不存在”“暂不可查”和“网络失败”，必须使用 FOUND / NOT_FOUND / UNKNOWN 及证据。fetch_fills 必须声明分页、时间范围和交易 ID 的唯一域。

能力字段包括 supported_order_types、submit_transports、position_modes、margin_modes、reduce_only_semantics、conditional_orders、quantity_units、stop_trigger_sources、private_stream_bootstrap、rate_limits、source_delay、liquidation_coverage。以 (exchange, region, environment, account_mode, market_type, sdk_version) 为配置维度。

## 3. 账户接入流程

1. 管理员选择交易所、注册地区、环境、账户类型和希望覆盖的账户域；不只输入三段密钥。
2. 服务端验证网络 / 域名、时钟、签名和只读权限；识别账户模式，生成不可变连接身份。网络错误不能误判“密钥无效”。
3. 获取市场规格、账户设置与钱包域，建立 equity_scope_key。Bitget UTA / OKX 统一交易账户不可按 spot / swap 各算一遍权益。
4. 私有流连接并开始缓冲；拉余额、仓位、普通挂单、条件挂单和必要成交；去重后应用增量，再进行一致性核对。
5. 状态从 CREATED → PROBING → SYNCING → LIVE；失败进入 AUTH_FAILED / DEGRADED / DISCONNECTED。REST 和 WS、公开与私有健康分别记录。
6. 只读验收通过后才可被管理员配置为交易候选；真正交易还需 E04 风控、安全和模拟验收，不自动提升权限。
7. 更新 / 删除凭据会停止旧会话并进行新一轮同步；历史事实不删除。

## 4. CCXT 使用约定

- Binance Spot 与 USDⓈ-M 优先用明确的 binance / binanceusdm 实例；Bitget 明确 uta 配置；OKX 根据账户配置设置参数。不能在一个连接中随意切 options.defaultType 导致缓存混用。
- 启用 SDK 限流，同时在应用层按 UID / IP / endpoint / 产品维护预算；enableRateLimit 不等于部署多个进程后自动满足总体限制。
- 精度来源为 load_markets 与原生规格；使用 amount_to_precision / price_to_precision 后仍检查最小单、名义金额和用户允许的调整。precision 字段不能一律解释成小数位数。
- SDK 返回的 free / used / total 不能自动当作各所统一的 NAV。必要时读取 info 中经文档核对的权益字段，并保存映射版本。
- 原生订单参数只由适配器生成，前端不能任意透传 params 或自定义请求 URL。
- 同一账户共享限流 / 会话管理；避免为每个标的新建一组私有连接。退出或重连必须 await close，防止残留 socket。
- 原生扩展不独立创建另一本订单账；所有结果回到相同标准订单、成交和审计模型。

## 5. 签名、时钟与环境

| 所 | REST 认证概要 | WS 认证概要 | 必须注意 |
|---|---|---|---|
| Binance | API key header + 按密钥算法签名参数；常用 HMAC-SHA256 query 签名，含 timestamp / recvWindow | 现货采用签名订阅或经验证会话方式；USDⓈ-M 按其私有流规范 | 现货 listenKey 旧教程已失效；不能套到合约 |
| Bitget | ACCESS-KEY / SIGN / TIMESTAMP / PASSPHRASE；时间+方法+路径+query+body 的 HMAC-SHA256 后 Base64 | login 签名路径与 REST 不同；经典和 UTA 校验 | 官方 WS 时间单位描述有冲突，见 Bitget 文档阻断项 |
| OKX | OK-ACCESS-KEY / SIGN / TIMESTAMP / PASSPHRASE；ISO 时间+方法+requestPath+body 签名后 Base64 | login 使用秒时间戳 + GET + /users/self/verify | REST 时间格式不能照搬 WS；模拟与生产标识不同 |

HMAC、RSA、Ed25519 选择取决于密钥类型；优先让固定版本 SDK 执行签名，并用官方样例做离线 fixture。签名前后的 URL 编码、query 顺序、空 body 与 JSON 序列化字节必须一致。签名示例一律使用假凭据。

时钟服务记录 server_time_offset 与往返延迟，交易签名使用经验证偏移；过大偏差暂停写操作。业务 freshness 以本地单调时钟计时；外部时间用于排序，但不能因源时钟漂移判定“未来行情永不过期”。

环境配置是一组整体：REST、公共 WS、私有 WS、交易 WS、API key 类型、模拟 header、允许市场和可用功能。模拟失败不能自动切生产 URL 或换用生产凭据。

## 6. 盘口、订阅与数据恢复

每所按文档选择 snapshot / delta、sequence / checksum 规则。增量到达但初始快照未建立时先缓冲；超过容量则丢弃该盘口并重新同步。先前 epoch 的增量不能应用到新快照。

币安按 U / u（合约另含 pu）衔接；Bitget 按具体频道和版本使用 seq / pseq / snapshot，checksum 规则不能照搬旧版；OKX 按 prevSeqId / seqId 与该频道规则处理，并按文档允许的序列重置重建。规则详见三所文档。

订阅管理限制同时连接、频道数量与控制消息频率；心跳按上游要求响应。指数退避加入抖动，认证失败不无限重连，限流时遵守 retry-after / ban 信息。连接轮换先同步新连接再交接；若不能无缝交接，明确展示数据间隙。

私有流重连后重新拉取完整仓位与挂单，并从上次水位之前的重叠区间回补成交 / 资金账单。仅按更新时间大于上次时间查询可能漏掉同毫秒或迟到记录，应按分页游标和 ID 去重。历史保留窗口不足时标记账本不完整并请求人工核对。

## 7. 数量、开平与费用

内部显示数量同时保留币数和合约张数。线性合约的 base_quantity = contracts × contract_size，只有市场确实以基础币计面值时适用；币本位等非线性产品留待独立适配。下单金额和持仓口径由原生规格决定，不从交易对名字猜测。

建立经测试的方向映射表：用户意图 OPEN_LONG / CLOSE_LONG / OPEN_SHORT / CLOSE_SHORT → side + positionSide / posSide + tradeSide + reduceOnly。不同模式参数不一定能同时出现；reduceOnly 在双向模式可能不可用，必须采用经过验证的专用平仓语义。

市价买入可能按报价币金额，市价卖出可能按基础币数量；统一 API 必须带 unit。止盈止损分别描述触发价格源、触发价、执行类型、委托价、关联仓位及平仓语义。原生条件单可用性需单独探测；本地软件止损在断网时可能不执行，不能伪装成交易所托管保护单。

费用记录原始币种和返佣符号；资金费以账单事实为准；市场费率估算不作为实际成本账。所有精度修正、预算预留和成交后释放都应可审计。

## 8. 错误分类与验收证据

AUTH / PERMISSION：停止对应私有连接并告警；CLOCK：校准后重新签名，仅对安全读操作自动重试；RATE_LIMIT：按预算退避；VALIDATION：明确拒绝，不重试；NETWORK：读可退避，写进入不确定性判断；EXCHANGE_UNAVAILABLE：熔断并保留已知状态；UNKNOWN：对账，不能用 0 / 空列表掩盖。

每个连接器交付：官方资料日期、SDK版本、账号模式、域名配置、市场样本、脱敏签名 / 报文 fixture、模式映射、订阅覆盖、恢复报告、限流报告和未支持清单。账户私有读取、模拟交易、条件单、紧急退出各有独立 PASS / FAIL / NOT_RUN，不能用一个“连接成功”代替。
