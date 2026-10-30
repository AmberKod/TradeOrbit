# OKX / 欧易接入实现说明

核对日期 2026-10-30；范围：API v5 交易账户及可选只读资金账户、现货与 USDT 线性永续。账户所在地区与账户等级会影响域名、产品、保证金和订单参数，不能只凭密钥连通判断全部可用。

## 1. 资料与代码依据

官方：[API v5 文档](https://www.okx.com/docs-v5/en/)、[最佳实践](https://www.okx.com/docs-v5/trick_en/)、[更新日志](https://www.okx.com/docs-v5/log_en/)。接口路径和字段另与本地 ccxt/ts/src/okx.ts、pro/okx.ts 对照。Hummingbot 对应 connector/exchange/okx 和 connector/derivative/okx_perpetual 可用于订单跟踪设计参考。

## 2. 域名、环境和认证

当前官方文档给出的生产 REST 入口包括 https://openapi.okx.com；历史 SDK 和部分配置使用 https://www.okx.com。部署时必须以注册地区当前文档与已验证 SDK 配置确定，不静默替换 hostname。生产 WS 常用 wss://ws.okx.com:8443/ws/v5/public、/private、/business；端口和地区档案按实际环境验证。

模拟使用独立 Demo API key，REST 附 x-simulated-trading: 1；WS 使用模拟档案，例如 wspap.okx.com 的对应 public / private / business 路径。仅设置 header 不代表生产 WS 自动变成模拟，必须验证两边的数据与账户一致。账号环境进入所有资产和订单主键，模拟资产不计入实盘总览。

REST 认证头：OK-ACCESS-KEY、OK-ACCESS-SIGN、OK-ACCESS-TIMESTAMP、OK-ACCESS-PASSPHRASE。REST 预串为 ISO8601 UTC 毫秒时间 + UPPER_METHOD + 含query的requestPath + 实际body，HMAC-SHA256 后 Base64。POST body 序列化后再签，不可签一种 JSON 却发送另一种。

WS login 使用秒级时间戳，预串为 timestamp + GET + /users/self/verify，注意 users 是复数；不能复用 REST 时间格式。只有 login ACK 通过才订阅 private channel，订阅 ACK 与初始数据就绪分开记录。

## 3. 账户配置与权益域

读取 GET /api/v5/account/config，记录账户级别、posMode、保证金模式和交易权限。初期在连接档案中明确支持的 Spot / Futures / 多币种保证金模式；Portfolio Margin / 组合保证金只有经过独立风控口径验证后才启用交易。

OKX 的交易账户可能在同一个权益域内同时持有现货与永续，不应创建“现货 NAV”与“合约 NAV”再简单相加。GET /api/v5/account/balance 的总权益用于该域聚合，details 用于资产拆分；adjEq 等抵押或可用口径不能直接替代资产市值。资金账户通过 GET /api/v5/asset/balances 单独查询并按覆盖配置纳入，避免遗漏或重复。

强平价和保证金率与账户模式、全仓 / 逐仓有关；保留原生风险字段及其解释。字段空或为不适用时显示未知 / 不适用，不能写成价格 0 或风险率 0。账户能读取并不代表有衍生品交易资格。

## 4. REST 接口映射

| 能力 | API v5 路径 | 处理 |
|---|---|---|
| 时间 / 产品 | GET /api/v5/public/time；GET /api/v5/public/instruments | instType=SPOT / SWAP，缓存 instId、tickSz、lotSz、minSz、ctVal、ctValCcy 和状态 |
| 账户配置 / 余额 | GET /api/v5/account/config；GET /api/v5/account/balance | 与连接身份、权益域关联 |
| 仓位 | GET /api/v5/account/positions | 按 instId、posSide、保证金信息归一 |
| 普通下单 | POST /api/v5/trade/order | 自定义 clOrdId 在发送前持久化 |
| 普通查单 / 撤单 | GET /api/v5/trade/order；POST /api/v5/trade/cancel-order | 按 ordId / clOrdId 和 instId 查询 |
| 普通挂单 / 历史 | GET /api/v5/trade/orders-pending；/api/v5/trade/orders-history；/api/v5/trade/orders-history-archive | 查清可查询时间与分页，历史不足标覆盖缺口 |
| 成交 | GET /api/v5/trade/fills；/api/v5/trade/fills-history | 按实际成交 ID 作用域去重并保留账单关联 |
| 资金与费用账单 | GET /api/v5/account/bills；/api/v5/account/bills-archive | 区分资金费、费用、划转和交易结果 |
| 资金账户 | GET /api/v5/asset/balances；充提历史按 asset 相关只读端点 | 可选资产覆盖，不提供自动 transfer / withdraw |
| K 线 / 深度 / 成交 | GET /api/v5/market/candles；/api/v5/market/books；/api/v5/market/trades | 与公开 WS 配合初始化 / 回补 |
| 费率 / OI | GET /api/v5/public/funding-rate；/api/v5/public/open-interest | 实际结算时间和 oi 单位必须保存 |
| 杠杆 | GET /api/v5/account/leverage-info；POST /api/v5/account/set-leverage | 明确 mgnMode、instId、必要时 posSide |
| 条件单 | POST /api/v5/trade/order-algo；GET /api/v5/trade/orders-algo-pending；POST /api/v5/trade/cancel-algos | 条件单 algoId 与触发普通单 ordId 分开建账 |

订单或批量请求同时检查顶层 code 与每项 sCode；顶层成功不代表每一项委托均成功。保存 sMsg 的脱敏信息和失败分类。撤单成功同样不等于已平仓。

## 5. 合约张数与订单映射

OKX 永续下单 sz 常表示合约张数，不是用户界面输入的 BTC 数量。线性且 ctVal 以基础币计价时，base_quantity = sz × ctVal；只有满足 ctValCcy 条件时才使用此公式。不能把 ctVal 当价格或把 lotSz 当小数位数。

预检同时返回：用户输入的币数 / 名义金额、最终张数、面值、交易步长、预计名义金额、调整与余量。按 lotSz 和 minSz 校验；无法精确表达时要求使用明确的规格调整结果，不能默默扩大风险。市价现货买入的 tgtCcy 等数量语义与合约不同，需单独映射。

| 账户模式 | 开多 / 平多 | 开空 / 平空 |
|---|---|---|
| net_mode | BUY / SELL，净额变化；平仓采用经验证的 reduceOnly | SELL / BUY，净额变化；防止穿仓变反向 |
| long_short_mode | posSide=long，side=buy / sell | posSide=short，side=sell / buy |

每单明确 tdMode（cash / cross / isolated 等被允许组合），双向模式明确 posSide。不能默认所有单均 cross，也不能把不合法 reduceOnly 附到每种模式。杠杆设置与模式修改是单独、可审计的配置操作。

止盈止损保留触发价源 last / index / mark、触发价和执行价语义。交易所条件单、附加保护单和本地监控触发单分别展示；紧急退出同时检查普通挂单与 algo 条件单，避免平仓后遗留触发单重新开仓。

## 6. WebSocket 与恢复

公开订阅根据 instType / instId 选择 tickers、trades、candles、books 或 books5、funding-rate、open-interest、liquidation-orders 等实际允许频道；某些频道使用 business 路径，不能全塞 public。频道路径由当前文档和固定 SDK 的 getUrl 规则核对。

盘口优先使用普通公开频道；高频档位可能要求身份 / VIP 权限，首期不默认依赖它们。保存 snapshot / update 类型与 seqId / prevSeqId；按照该频道文档判断无更新心跳、序列重置和重连，不能简单把每个相等序列号都当错误。校验失败立即重建，不继续展示旧深度为 LIVE。

私有频道包含 account、positions、orders 等。orders 不作为当前全部订单的初始快照来源：先订阅缓冲并拉普通 / 条件挂单、仓位与近期成交，再对账。账户 / 仓位的订阅快照也必须按该频道覆盖范围解读。

爆仓频道并非全部强平明细来源；不以其累计金额充当全市场实际总量。记录 instId、方向、大小单位、源事件时间和推送限制；由 instrument contract_size 转换，不能混用不同类型合约的原始 sz。

收到空闲连接的 ping / pong 按文档处理；检查订阅 ACK、错误事件、权限和连接限制。新会话恢复前 account=RECONCILING，读模型带质量状态；不能因 WS 重连成功就自动恢复策略交易。

## 7. 验收清单

地区域名和模拟标识；交易 / 资金账户权益域；Spot / SWAP 的数量单位；net / long_short 与 cross / isolated 参数；clOrdId 查单；部分成交期间撤单；普通 / algo 单父子关联；盘口序列与频道权限；资金费账单；私有流恢复、未知订单和数据覆盖。不同账户级别分别记录 PASS / FAIL / NOT_RUN，未验证的组合保持禁用。
