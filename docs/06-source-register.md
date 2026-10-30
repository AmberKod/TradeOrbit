# TradeOrbit 依据、版本与待验证事项

编制日期：2026-10-30，Asia/Shanghai。接口事实来自当日官方文档检索与本地源码静态阅读。WEB_CHECKED / LOCAL_SOURCE_CHECKED 表示资料已核对，不代表账号联调通过；所有私有能力和交易测试当前均为 NOT_RUN。

## 1. 本地参考版本

| 项目 | 路径 | 本轮看到的提交 / 日期 | 本地许可证 |
|---|---|---|---|
| CCXT | E:/github_repo/ccxt | 5ad061c / 2026-10-30；package.json 4.5.91 | MIT，LICENSE.txt |
| Hummingbot | E:/github_repo/hummingbot | 9af100d / 2026-09-22 | Apache-2.0，LICENSE |
| Freqtrade | E:/github_repo/freqtrade | 693d246 / 2026-10-30，提交说明为 2026.11-dev | GPL-3.0，LICENSE |
| FreqUI | E:/github_repo/frequi | 4e1717a / 2026-10-29 | GPL-3.0，LICENSE |
| TradeOrbit | E:/github_repo/TradeOrbit | 文档开始前 4ea8d32 / 2026-10-30 | 项目许可尚待仓库所有者选择 |

许可证名称只是本地文件记录。本方案将依赖使用、设计借鉴和直接复制源码分别登记；如果计划复制第三方实现，先明确具体文件、许可证 / NOTICE 与项目发布方式。本轮没有复制上述项目代码，也未选择 TradeOrbit 的分发许可。

## 2. 官方资料登记

| 编号 | 官方资料 | 本轮用于核对 |
|---|---|---|
| B01 | [Spot Change Log](https://developers.binance.com/docs/binance-spot-api-docs/CHANGELOG) | 2026-02-20 移除旧现货 listenKey 流 |
| B02 | [Spot User Data Stream Requests](https://developers.binance.com/docs/binance-spot-api-docs/websocket-api/user-data-stream-requests) | 签名订阅及 subscriptionId |
| B03 | [USDⓈ-M WebSocket Market Streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams) | 频道与行情规则；结合变更日志，不单用旧通用 URL |
| B04 | [Derivatives Change Log](https://developers.binance.com/docs/derivatives/change-log) | Futures 类别路由、接口版本与条件单变更 |
| B05 | [New Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order) | 普通下单与模式约束 |
| B06 | [New Algo Order](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Algo-Order) | 条件单独立服务 |
| B07 | [USDⓈ-M User Data Streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/user-data-streams) | 合约私有流与续期；不能套现货迁移 |
| BG01 | [UTA Upgrade Guide](https://www.bitget.com/docs/uta/upgrate-guide) | v2 / v3、账户和接口分支 |
| BG02 | [Quick Start](https://www.bitget.com/docs/uta/quick-start) | REST / WS 域名、认证和时间说明 |
| BG03 | [HMAC Sample](https://www.bitget.com/docs/uta/signature-sample/hmac) | 签名字节、query / body |
| BG04 | [Demo Trading](https://www.bitget.com/docs/uta/demo-trading) | 模拟 API key、标识和 WS |
| BG05 | [WS Connection](https://www.bitget.com/legacy-docs/uta/websocket/general/Connection) | login 文案和代码样例存在时间单位歧义 |
| BG06 | [Order Book Channel](https://www.bitget.com/legacy-docs/uta/websocket/public/Order-Book-Channel) | checksum 变更、books50 环境分期 |
| BG07 | [Liquidation Channel](https://www.bitget.com/legacy-docs/uta/websocket/public/Liquidation) | 1 秒、最多 2 条 / 标的、quote qty 和采样 |
| BG08 | [Account Assets](https://www.bitget.com/legacy-docs/uta/account/Get-Account-Assets) | UTA 资产明细 /api/v3/account/assets |
| BG09 | [Account Overview](https://www.bitget.com/legacy-docs/uta/account/Get-Account) | UTA 总览 /api/v3/account/account |
| BG10 | [Place Order](https://www.bitget.com/docs/uta/trade/Place-Order) | v3 普通下单及端点独立限额 |
| O01 | [OKX API v5](https://www.okx.com/docs-v5/en/) | 域名、模拟、账户 / 订单 / 频道与参数；子端点另与本地源码交叉检查 |
| O02 | [OKX Best Practice](https://www.okx.com/docs-v5/trick_en/) | 作为接入时进一步核对入口，细节需 E02 复核 |
| O03 | [OKX Change Log](https://www.okx.com/docs-v5/log_en/) | 作为上线前版本复核入口 |

官方站点正在迁移页面；部分 api-doc / docs 链接会跳转 catalog，部分资料仍列在 legacy-docs。实际开发记录最终 URL、页面日期和脱敏样例，不以页面路径中是否带 legacy 判断接口已经停用。端点映射还使用了用户下载的本地 CCXT 实现；表中未逐项单独在线验证的历史 / 账单 / 高级类型由 E02 / E04 再冻结。

## 3. 本地源码证据

- CCXT：ts/src/pro/binance.ts 的 describeData、getWsUrl、getPrivateWsUrl、ensureUserDataStreamWsSubscribeSignature；pro/binanceusdm.ts 的继承和默认线性市场。
- CCXT：ts/src/pro/bitget.ts 的 has、v2 / v3 URL、uta 分支、authenticate；ts/src/bitget.ts 的 handleUTAAndParams 和 REST 映射。
- CCXT：ts/src/pro/okx.ts 的 has、getUrl、watchPositions、watchOrders；ts/src/okx.ts 的 ctVal / lotSz 与合同数量处理。
- Hummingbot：connector/exchange_py_base.py 的 ClientOrderTracker、lost order 轮询；strategy_v2/executors/twap_executor/ 的拆单、撤单和依赖；setup.py 的 Cython 构建。
- Freqtrade：rpc/api_server/deps.py 的 RPC / exchange 配置、api_ws.py 的消息流、exchange/exchange.py 的 ccxt.pro 接入。
- FreqUI：src/stores/ftbotwrapper.ts 的多 bot 聚合、ftbot.ts 的余额 HTTP 请求与 WS 通知，composables/api.ts 的 API 客户端。

## 4. 决策与上线阻断项

| 编号 | 事项 | 当前结论 / 处理 | 关闭条件 |
|---|---|---|---|
| V-01 | 实际注册地区与账户模式 | 尚未提供；配置不可默认猜测 | 管理员登记，能力探测与只读样例通过 |
| V-02 | Binance Spot 私有流迁移 | 旧 listenKey 不再采用，使用当前签名订阅 | 选定 SDK 与账号订阅 / 重连证据 |
| V-03 | Futures 新路由与条件单 | public / market / private 分开；algo 单独管理 | 各频道路由和普通 / 条件单生命周期验收 |
| V-04 | Bitget UTA WS 时间单位冲突 | 官方文案与样例 / CCXT 不一致，先验证固定 SDK 秒路径 | 对应环境成功 login、订阅与重连 fixture |
| V-05 | Bitget books50 / checksum | 环境与日期相关，不能照旧全局校验 | 所选频道的真实 snapshot / delta 样例和断序测试 |
| V-06 | Bitget 爆仓 | 采用当前限量推送和 quote qty 说明，修正旧 Beta 泛化结论 | 原生公共流样例、产品范围、单位和采样核对 |
| V-07 | OKX 地区域名和账户级别 | 官网 / SDK hostname 可能不同，不自动互换 | 注册地区对应 REST / WS / Demo 的明确证据 |
| V-08 | 钱包权益与现金流 | 共享域去重；缺流水时不发布完整收益口径 | 每所 NAV 对账与充提 / 划转配对样例 |
| V-09 | 三所开平和保护单语义 | 必须做账户模式组合测试，不统一机械 reduceOnly | 支持组合逐项通过 Demo 测试 |
| V-10 | 真实通知 / 交易授权 | 当前仅做设计，未授权实盘或外部发送 | 用户明确授权、凭据和发布门槛齐备 |
| V-11 | 高级市场与策略 | 币本位 / 期权 / 公开代码上传 / 马丁预置不在首版 | 独立需求和风控设计 |

## 5. 实测状态

本轮：本地源码静态阅读、官方文档核对、文档链接与需求覆盖检查。未安装依赖、未启动平台、未建立真实私有流、未下单、未发送通知。后续在每个工作包内填实际证据，不将“文档已写”当“功能已实现”。
