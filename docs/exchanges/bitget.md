# Bitget 接入实现说明

核对日期 2026-10-30；范围：经典账户 v2 与统一交易账户 UTA v3 的现货 / USDT 永续。两套接口是账户模式分支，不是可随意交换的请求版本。

## 1. 资料与源码

官方：[UTA 升级差异](https://www.bitget.com/docs/uta/upgrate-guide)、[快速开始](https://www.bitget.com/docs/uta/quick-start)、[HMAC 样例](https://www.bitget.com/docs/uta/signature-sample/hmac)、[模拟交易](https://www.bitget.com/docs/uta/demo-trading)、[UTA WebSocket 连接说明](https://www.bitget.com/legacy-docs/uta/websocket/general/Connection)、[盘口](https://www.bitget.com/legacy-docs/uta/websocket/public/Order-Book-Channel)、[爆仓频道](https://www.bitget.com/legacy-docs/uta/websocket/public/Liquidation)。部分旧链接会跳转新 catalog，应保存最终页面与核对时间。

本地：ccxt/ts/src/bitget.ts、pro/bitget.ts。Hummingbot 的 bitget_perpetual 常量主要使用 /api/v2/mix 路径，不能据此认为它已覆盖 UTA。

## 2. 账户分支和环境

连接配置保存 account_mode=CLASSIC / UTA；未经探测不能默认所有账号相同。本地 CCXT 支持 uta 选项，REST 还会在部分方法探测模式。TradeOrbit 将探测结果固定到连接档案，管理员变更后重建连接，避免同一订阅缓存混入两套账户域。

| 分支 | REST | 公共 / 私有 WS | 处理 |
|---|---|---|---|
| 经典 | https://api.bitget.com 下 v2 spot / mix | wss://ws.bitget.com/v2/ws/public；/v2/ws/private | 产品类型和账户域分别查询 |
| UTA | https://api.bitget.com 下 /api/v3 | wss://ws.bitget.com/v3/ws/public；/v3/ws/private | 统一钱包权益只计一次 |
| UTA Demo | 官方模拟 REST 标识与 Demo API key | wss://wspap.bitget.com/v3/ws/public；/v3/ws/private | 使用 paptrading: 1 等当日官方要求，独立密钥 |
| 经典 Demo | 以官方支持和已验证 SDK 配置为准 | v2 模拟流 / 模拟产品命名按能力选择 | 不把 v3 示例自动替换版本号后使用 |

模拟登录使用模拟 API key；生产 key 与模拟标识混用应被配置校验拒绝。连接健康、账户模式和 domain profile 展示到设置页。

## 3. 认证与时间单位冲突

REST headers：ACCESS-KEY、ACCESS-SIGN、ACCESS-TIMESTAMP、ACCESS-PASSPHRASE。REST 时间为毫秒；签名预串为 timestamp + UPPER_METHOD + requestPath + 可选问号及query + 实际JSON body，再用 secret 做 HMAC-SHA256 并 Base64。query 编码 / 排序和 body 序列化必须与发送字节一致，空 body 不能擅加大括号。

WS 登录签名路径使用 /user/verify，与 OKX 的 /users/self/verify 不同。本轮核对发现官方 UTA 连接文案称毫秒，而同页 Java 示例 / 1000 以及本地 CCXT authenticate 使用秒；这是需要联调消除的真实歧义，不能在规格中假装已经确定。

实施约定：优先使用固定 CCXT 版本已经实现的秒级登录路径，先在对应 Demo 环境验证；保存脱敏 login ACK 和时间样本。如果 UTA 环境不接受，依据当日官方说明独立验证 UTA profile，并形成 fixture 后再启用。不同单位不可运行时无限切换重试。此项是 Bitget 私有流 / 交易发布阻断项，不影响公开行情和离线开发。

## 4. REST 接口映射

| 能力 | 经典账户 | UTA | 业务说明 |
|---|---|---|---|
| 产品规格 | GET /api/v2/spot/public/symbols；/api/v2/mix/market/contracts | GET /api/v3/market/instruments | category / productType、数量单位和状态显式保存 |
| 账户余额 / 权益 | GET /api/v2/spot/account/assets；/api/v2/mix/account/accounts | GET /api/v3/account/assets；GET /api/v3/account/account | UTA assets 明细与 account 总览不能直接加总 |
| 当前持仓 | GET /api/v2/mix/position/all-position | GET /api/v3/position/current-position | 保留账户模式、方向与原生风险口径 |
| 下单 | POST /api/v2/spot/trade/place-order；/api/v2/mix/order/place-order | POST /api/v3/trade/place-order | clientOid 在首次发送前持久化 |
| 查普通单 | GET /api/v2/spot/trade/orderInfo；/api/v2/mix/order/detail | GET /api/v3/trade/order-info | clientOid / orderId 的查询能力分别验证 |
| 撤普通单 | POST /api/v2/spot/trade/cancel-order；/api/v2/mix/order/cancel-order | POST /api/v3/trade/cancel-order | 返回受理后仍需订单 / 成交确认 |
| 普通挂单 | 按 spot unfilled-orders / mix orders-pending | GET /api/v3/trade/unfilled-orders | 不代表所有策略 / 触发单 |
| 历史与成交 | spot / mix 对应历史和 fills | GET /api/v3/trade/history-orders；GET /api/v3/trade/fills | 根据真实分页、保留期重叠回补 |
| 资金账单 | 经典账户各产品账单 | GET /api/v3/account/financial-records | 分类入金、出金、划转、费用与资金费 |
| 条件单 / 止盈止损 | mix plan-order 等独立接口族 | UTA 当前策略 / 止盈止损接口族独立适配 | 未完成字段与模式验证前标 CAPABILITY_UNAVAILABLE |

OI、资金费率、杠杆 / 保证金设置由已核对的 SDK 方法及对应市场端点实现，不从 v2 URL 机械替换 v3。具体条件单类型和杠杆写参数需在 E04 的账户模式矩阵中冻结；普通交易上线不自动代表全部高级单可用。

## 5. WebSocket 字段与盘口迁移

经典频道使用 channel / instId 等字段；UTA 使用 topic / symbol，产品标识的大小写也有差异。订阅 ACK 成功后才标记 SUBSCRIBED，收到有效快照或实时数据后才标 LIVE。

UTA 公共订阅形状示例：

~~~json
{"op":"subscribe","args":[{"instType":"usdt-futures","topic":"books5","symbol":"BTCUSDT"}]}
~~~

示例只说明已核对频道的格式；不能将该格式用于 v2。私有账户、持仓、订单和成交 topic 的过滤范围按当前官方 schema 与 SDK 实际生成请求固化；不能猜默认 symbol。初次订阅是否给完整快照按频道定义判断，REST 引导始终保留。

2026 年盘口文档有两项需要显式处理：UTA 说明自 2026-05-19 起不应依赖原 checksum；books50 在 2026-10-26 说明中于模拟环境转为增量，正式环境当时标为后续更新。因此每个环境记录频道版本，观察 action、seq / pseq 和 snapshot 类型。不能仅按“books50 永远是快照”写死，也不能假定正式 / 模拟已同步切换。

恢复规则：按该频道的 seq / pseq 衔接；首个 snapshot 重置本地书；连续性失效或服务端重置时重新同步。若 SDK 版本仍对某频道强制旧 checksum，应先用 fixture 复现，选择修复 / 升级已验证版本，不能全局关闭所有交易所的校验。

## 6. 爆仓数据与之前结论的修正

当前官方 UTA 爆仓说明列出 topic=liquidation，约 1 秒推送；每个交易对每次最多推送 2 条，超过时采样；qty 表示 quote 成交额。它不支持按指定交易对逐一订阅，实际产品范围按当前 instType 说明核对。

因此不再沿用此前“只有 USDT、非实时 Beta”的笼统结论。当前已核对的是上述限量推送说明；频道稳定性与账号 / 环境覆盖仍需实测。UI 显示源事件与金额、采样说明和状态；不能把 qty 当基础币数量再乘价格，造成金额重复放大。CCXT 本地 Bitget pro 未实现该统一订阅，优先评估独立公共原生适配并纳入相同事件协议。

## 7. 开平、资产与模式

经典合约的 side、tradeSide、holdSide / posMode 与 UTA 的参数结构必须分别建立映射；双向模式的“平多”不能仅由 SELL 推断为开空。reduceOnly 的允许场景和大小写由各分支适配，禁止原生字段从页面任意透传。

杠杆与保证金模式是受约束配置动作。只减仓与紧急退出必须结合最新仓位、挂单和条件单，不按创建策略时的旧仓位平仓。仓位模式不匹配时拒绝并显示原因，不能为使请求成功而自动切模式。

UTA 账户总览的权益、保证金风险与资产明细分开建模；同一钱包的现货资产和永续 PNL 不重复计入 NAV。经典现货与合约按实际独立权益域计量。资金流水不全时，资金流调整后收益覆盖标记不完整。

## 8. 限流、错误和验收

按端点声明分别维护 UID / IP 预算；例如当前 UTA 普通下单文档的限额不能外推为账户查询或所有端点的统一限额。HTTP 成功仍需检查业务 code；Bitget 常见成功码为 00000，失败的业务码归类后处理。对不确定的写响应按 clientOid 对账。

验收必须覆盖：经典 / UTA 两套 wallet scope、Demo 与生产隔离、WS 时间戳歧义、topic 字段与产品大小写、盘口切换、爆仓 qty 单位和采样、两种持仓模式、条件单独立生命周期、重连补账和重复成交。未能验证的模式保持禁用，而不是宣称“支持 Bitget 全部能力”。
