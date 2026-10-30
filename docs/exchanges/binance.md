# Binance 接入实现说明

核对日期 2026-10-30；范围：Binance 全球站 API 的现货与 USDⓈ-M USDT 永续。Binance.US、Portfolio Margin、币本位和期权不是同一配置，未经专项适配不得复用本文件。

## 1. 资料与本地代码

官方：[Spot 变更日志](https://developers.binance.com/docs/binance-spot-api-docs/CHANGELOG)、[Spot 私有流请求](https://developers.binance.com/docs/binance-spot-api-docs/websocket-api/user-data-stream-requests)、[衍生品变更日志](https://developers.binance.com/docs/derivatives/change-log)、[USDⓈ-M 行情流](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams)、[新普通订单](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order)、[新条件订单](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order)。

源码：ccxt/ts/src/binance.ts、binanceusdm.ts、pro/binance.ts、pro/binanceusdm.ts。重点检查 pro/binance.ts 的 getWsUrl、getPrivateWsUrl、ensureUserDataStreamWsSubscribeSignature、authenticate、handleOrderUpdate。

## 2. 环境、密钥与鉴权

| 环境 / 产品 | REST 与流配置 | 接入要求 |
|---|---|---|
| 生产 Spot | api.binance.com；公开流 stream.binance.com；交易 / 私有订阅 WS API ws-api.binance.com | 按账户地区确认域名，不将 Binance.US 当作同站 |
| 生产 USDⓈ-M | fapi.binance.com；公开 / 市场 / 私有流 fstream.binance.com 的不同路径 | 明确线性合约与账户模式 |
| Spot Testnet | testnet.binance.vision 对应的 REST、公开流和 WS API | 账号与密钥独立，资产可能重置 |
| Futures Demo | 官方 Futures Demo 配置，独立凭据；SDK 示例使用 demo-fapi / fstream 测试域名组合 | 实际 URL 由环境档案固定并测试，不从 Spot Testnet 推导 |

生产 REST 基址为 https://api.binance.com 和 https://fapi.binance.com。公开 Spot WS 常用 wss://stream.binance.com:9443/ws；Spot WS API 为 wss://ws-api.binance.com:443/ws-api/v3。各模拟基址必须从当日官方页面 / SDK 环境配置核对，记录在 CapabilityProfile，不能以登录到网页模拟盘推断所有 API 能力相同。

首期只读 key；交易期增加必要的 Spot / Futures 交易权限并限制 IP；提现和自动划转不在应用允许动作中。常用 HMAC key 的 REST 签名为 HMAC-SHA256(secret, 实际发送的编码参数串)，以 X-MBX-APIKEY 发送 key。timestamp 使用毫秒，recvWindow 由配置与时钟偏移约束。RSA / Ed25519 key 使用对应算法，禁止仅按字符串长度猜密钥类型。

## 3. REST 能力映射

| 能力 | Spot | USDⓈ-M | 业务处理 |
|---|---|---|---|
| 时间 / 市场 | GET /api/v3/time；/api/v3/exchangeInfo | GET /fapi/v1/time；/fapi/v1/exchangeInfo | 缓存 filters 和市场状态，记录规格版本 |
| 深度 / K 线 | GET /api/v3/depth；/api/v3/klines | GET /fapi/v1/depth；/fapi/v1/klines | 初始化与断线回补 |
| 账户权益 | GET /api/v3/account | GET /fapi/v3/account | 现货 free+locked；合约权益按已核对字段，不再加一次 PNL |
| 仓位 | 不使用合约仓位模型 | GET /fapi/v3/positionRisk | 保留 positionSide、marginType、entryPrice、markPrice、liquidationPrice |
| 普通下单 | POST /api/v3/order | POST /fapi/v1/order | 先交付 LIMIT / MARKET |
| 查单 / 撤单 | GET /api/v3/order；DELETE /api/v3/order | GET /fapi/v1/order；DELETE /fapi/v1/order | 可按 origClientOrderId 查询已有委托 |
| 普通挂单 | GET /api/v3/openOrders | GET /fapi/v1/openOrders | 不代表包含全部条件单 |
| 成交 / 账单 | GET /api/v3/myTrades；资金流水按单独 SAPI 能力接入 | GET /fapi/v1/userTrades；GET /fapi/v1/income | 分页 / 时间范围按端点文档，资金费单独分类 |
| OI / 费率 | 不适用 | GET /fapi/v1/openInterest；GET /fapi/v1/premiumIndex；历史资金费 GET /fapi/v1/fundingRate | 记录量纲、标记价、费率时间与结算时间 |
| 杠杆 / 模式 | Spot 不提供合约杠杆设置 | POST /fapi/v1/leverage；/fapi/v1/marginType；/fapi/v1/positionSide/dual | 只在显式配置流程操作，不能每笔单自动切模式 |
| 条件单 | 按 Spot 订单类型另适配 | POST/GET/DELETE /fapi/v1/algoOrder；GET /fapi/v1/openAlgoOrders | 独立生命周期，触发后关联普通子订单 |

表中路径是产品映射，不代表每个子接口已在当前账号验证。币安近年的条件单已独立到 Algo 服务；不能继续把所有 STOP / TAKE_PROFIT / TRAILING 类型一律提交给普通 /fapi/v1/order。上线前复查对应类型、触发价源和响应字段。

## 4. WebSocket 与版本迁移

### Spot

2026-02-20 官方变更明确移除了现货旧 listenKey 用户流接口。TradeOrbit 的现货接入使用 WebSocket API 的 userDataStream.subscribe.signature，或经验证的会话订阅方式；不再使用 /api/v3/userDataStream 旧流程。收到订阅确认后保存 subscriptionId，并兼容订阅封装中的 event 字段。账户事件、订单事件与订阅终止分别处理。

公开频道按小写原生 symbol 订阅，例如 btcusdt@trade、btcusdt@depth@100ms、btcusdt@kline_1m；是否使用 combined stream 由连接预算决定。控制消息和心跳也占连接预算，遵守当日官方限制。

### USDⓈ-M

当前变更日志规定按类别拆分路径，本地 CCXT 也有对应重写：

| 类别 | 生产 WS 路径 | 常见数据 |
|---|---|---|
| public | wss://fstream.binance.com/public/ws | depth、bookTicker、trade 等高频公开信息 |
| market | wss://fstream.binance.com/market/ws | K 线、ticker、标记 / 费率、强平等；具体流路由按文档核对 |
| private | wss://fstream.binance.com/private/ws?listenKey=... | 用户账户与订单事件 |

不能把所有频道继续放到旧 /ws 路径，也不能把现货的签名订阅流程照搬到 Futures。Futures 的 listenKey 创建 / 续期按 /fapi/v1/listenKey 与当日私有流文档执行，续期失败后进入恢复流程。解析 ACCOUNT_UPDATE、ORDER_TRADE_UPDATE、过期或断连事件；持仓和余额增量都不能代替全量 REST 对账。

普通 Binance 配置内同时出现期权与 USDⓈ-M 路径时，必须按 market_type 筛选，避免使用 option 类别路由去订阅永续。

## 5. 盘口与爆仓处理

Spot 深度：先缓冲增量，再获取 REST 快照 lastUpdateId；丢弃 u 不大于快照水位的旧消息；首个增量必须覆盖快照后的下一更新，随后检查连续性。USDⓈ-M 使用其文档要求的 U / u / pu 衔接规则，不能直接复制现货的判断式。发现缺口使盘口 INVALID，清理旧 epoch 并重新初始化。

强平流 forceOrder 采用采样推送，每个标的的时间窗口不保证包含所有事件。页面显示“数据源已推送的强平事件”，不能将其金额之和称为 Binance 全部爆仓总量；事件数量、成交状态、单位和时间均保留原字段。

## 6. 开平、精度与资产

按 exchangeInfo 的 PRICE_FILTER、LOT_SIZE、MARKET_LOT_SIZE、MIN_NOTIONAL / NOTIONAL 等实际 filters 验证，不从 precision 猜步长。市价买单的 quoteOrderQty 与 base quantity 语义分开。

| 模式 | 意图 | 映射方向 |
|---|---|---|
| 单向 | 开多 / 开空 | positionSide=BOTH，side=BUY / SELL，按当前净仓计算开平影响 |
| 单向 | 减仓 | 反向 side + 支持的 reduceOnly，按最新持仓限量 |
| 双向 | 开多 / 平多 | positionSide=LONG，side=BUY / SELL |
| 双向 | 开空 / 平空 | positionSide=SHORT，side=SELL / BUY |

双向模式不能机械附加所有 reduceOnly 参数；按该端点合法组合验证。持仓模式变更通常有账户级影响，有仓位 / 挂单时必须检查限制。

Spot 钱包与 Futures 钱包按物理账户域分别计量。合约 totalMarginBalance / totalWalletBalance / totalUnrealizedProfit 的选取在快照模型中明确，只选一种不重复的权益口径。外部资金记录和钱包间划转需要补充授权的数据源，无法覆盖时收益曲线标为不完整。

## 7. 限流、错误与验收

读取 exchangeInfo 的 rateLimits 与响应头权重 / 订单计数；多 worker 共享 IP / UID 预算。HTTP 429 / 418 按提示退避，不重连轰炸。签名或时钟错误先校验字节串和 server offset；订单写请求超时、5xx 和不确定响应进入 UNKNOWN 后查询，不统一认为未受理。

验收清单：Spot 签名订阅、Futures 三类别路由、私有流续期、两种持仓模式、普通 / 条件单分别撤查、精度过滤、部分成交与响应丢失、资金费账单、断线回补及资产去重。账号不支持的项标 UNSUPPORTED；未执行的标 NOT_RUN。任何域名迁移或条件单变更未核对清楚时不开放对应实盘能力。
