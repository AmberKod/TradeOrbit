# E02-M2.1 私有账户手动只读接入

日期：2026-10-31。范围：管理员手动验证 → 签名 GET → 分域快照 → 页面展示。E02 和 M2 总体仍进行中；本增量没有私有 WS、定时对账或交易执行。

## 1. 使用与支持矩阵

账户页先保存 API 凭据，再由管理员点击“验证并同步”；保存配置、打开页面或重启服务不会请求交易所。其他工作空间成员可查看已保存快照。每个连接的模式、环境和地区保持不可变；选错时新建连接，不自动换环境。

| 交易所 / 配置 | 当前环境 | 只读范围 | 边界 |
|---|---|---|---|
| Binance / STANDARD / GLOBAL | LIVE | 现货钱包、USDⓈ-M 钱包及未平仓持仓 | 不含币本位、组合保证金、理财与资金流水 |
| Bitget / CLASSIC / GLOBAL | LIVE、DEMO | v2 现货钱包、USDT 合约钱包与持仓 | 以 v2 读取兼容性作证据，完整升级状态识别待补 |
| Bitget / UTA / GLOBAL | LIVE、DEMO | v3 设置、共享钱包、USDT 合约持仓 | 只接入 accountMode=unified；hybrid 不支持；升级/切换中停止后续读取 |
| OKX / UNIFIED / GLOBAL | LIVE、DEMO | 账户配置、统一交易钱包、资金钱包、SWAP 持仓 | 保留 acctLv；不包括借贷账本、交割及期权持仓 |

Binance DEMO 暂不接入：Spot Testnet、Spot Demo 与 USDⓈ-M Demo 的密钥/域名需要独立产品配置，不能把一套凭据静默复用。UNKNOWN 模式、非 GLOBAL 地区在发出请求前拒绝。OKX 区域站及 Bitget hybrid 需要单独适配和验收，不回退全球站。

当前支持 HMAC-SHA256 凭据。RSA / Ed25519 不支持。只读请求成功不等于密钥只有只读权限；建议在交易所创建只读密钥并设置后端出口 IP 白名单。Bitget UTA 需要相应账户管理与交易信息读取权限。

## 2. 实际端点与签名

所有端点固定在后端清单；客户端不能传入 URL、path 或任意 params。仅发送 GET，不创建 listenKey，不修改交易所设置，不下单、转账、提币或通知外部渠道。禁止跟随重定向；TLS 校验保持开启。

| 配置 | 固定主机 | 私有 GET |
|---|---|---|
| Binance | api.binance.com | /api/v3/account |
| Binance | fapi.binance.com | /fapi/v3/account、/fapi/v3/positionRisk |
| Bitget CLASSIC | api.bitget.com | /api/v2/spot/account/assets、/api/v2/mix/account/accounts、/api/v2/mix/position/all-position |
| Bitget UTA | api.bitget.com | /api/v3/account/settings、/api/v3/account/assets、/api/v3/position/current-position |
| OKX | www.okx.com | /api/v5/account/config、/api/v5/account/balance、/api/v5/asset/balances、/api/v5/account/positions |

Bitget 合约 query 固定 productType=USDT-FUTURES 或 category=USDT-FUTURES；OKX 持仓固定 instType=SWAP。其他产品不能视为已覆盖。

- Binance：X-MBX-APIKEY；query 包含 timestamp、recvWindow=5000，以 Secret 对实际 query 字节做 HMAC-SHA256，十六进制签名追加到 query。
- Bitget：毫秒时间戳 + GET + 含 query 的 requestPath，HMAC-SHA256 后 Base64；ACCESS-KEY / SIGN / TIMESTAMP / PASSPHRASE。DEMO 必须加 paptrading: 1。
- OKX：UTC 毫秒 ISO 时间戳 + GET + 含 query 的 requestPath，HMAC-SHA256 后 Base64；OK-ACCESS-* 四项头。DEMO 必须加 x-simulated-trading: 1。

先调用相应公开时间端点：Binance /api/v3/time、/fapi/v1/time；Bitget /api/v2/public/time；OKX /api/v5/public/time。按请求往返中点校正时差；校时 RTT 超过 5 秒或偏差超过 5 分钟拒绝。仅时钟错误重新校时、重签一次；认证、网络、限流错误不盲目重试。

## 3. 服务 API 与持久化

前缀 /api/v1，返回沿用 data / meta 包装，schema_version=1。

| 接口 | 权限 | 行为 |
|---|---|---|
| POST /accounts/{id}/verify | ADMIN + 会话 + Origin + CSRF | 唯一会请求私有交易所的入口，验证并保存本轮结果 |
| GET /accounts/{id}/snapshot | 当前工作空间成员 | 只读取本地已保存快照，不触发交易所请求 |
| GET /accounts/{id}/capabilities | 当前工作空间成员 | 返回状态、覆盖、时间与安全错误，不附带财务明细 |

新增 account_read_states：account_id 主键/外键、credential_version、state、scopes(JSON)、checked_at。只保存每账户各域的最新成功快照和最新尝试结果，不保存原始交易所响应、签名、密钥、UID 或 IP。迁移 0003_account_read_state 依赖 0002_market_watchlist；现有账户和加密凭据表不重建。

state 为 NOT_VERIFIED、VERIFIED、PARTIAL、FAILED。VERIFIED 仅表示此配置定义的所有 GET 契约在上次尝试成功，不表示已持续连接、全资产覆盖、密钥最小权限核验或可交易。

每个 scopes 条目包含 status、error_code、error_message、observed_at、age_seconds、freshness 和 data。data 中为 balances、positions 和过滤后的 metadata。capabilities 接口移除 data。

- 某域失败保留相同凭据版本的旧数据，明确标记 STALE；从未成功则 MISSING，不补零或空仓。
- 成功返回合法空数组可以表示该域确实没有余额/持仓；缺少必要字段或分页未覆盖属于失败。
- 快照超过 300 秒为 STALE。前端按接收时刻的单调时间累计年龄，切页重新打开不会恢复“新鲜”。
- 资产净值、历史曲线与去重聚合留待后续；不把各所钱包数字直接相加显示 NAV。

## 4. 金额、数量与风险口径

金额经 Decimal 处理并作为字符串传输；加总采用高精度上下文。拒绝 NaN、Infinity、异常大指数和非法数值；未知值保持 null。

- Binance 现货权益=free+locked；USDⓈ-M 使用 marginBalance，另存 walletBalance、availableBalance、unrealizedProfit，不重复叠加 PNL。
- Bitget 经典现货=available+frozen+locked；合约用 accountEquity；UTA 用每币种 equity，整个共享钱包只展示一次，不按 spot/swap 拆成两份。
- OKX 交易钱包使用每币种 eq，另保留 cashBal、availBal、upl；原生 totalEq 为 USD 口径元数据，不把它当作 USDT 余额再相加。资金钱包用 bal。
- Binance / Bitget 持仓数量为原生基础币数量；OKX SWAP 的 pos 保留 CONTRACT 张数，不猜测合约面值换算。方向与正数量分别展示。
- 强平价不适用、空字符串或非正值显示“—”；不能显示为有效零价格。
- Bitget 经典 marginRatio 与 OKX mgnRatio 保留来源定义；不统一套阈值。Binance v3 未返回的杠杆/保证金率保持未知，UTA mmr 不冒充持仓风险率。

## 5. 并发、安全与网络

同账户 Redis 锁 90 秒，手动同步至少间隔 30 秒；部署共享 Redis 按交易所控制每分钟最多 30 轮。全轮网络预算 45 秒，单次 HTTP 超时 8 秒（连接 4 秒），响应体最多 2 MB。

429 / 418 或对应业务码停止本轮剩余请求，并设置交易所级冷却。限流默认至少 120 秒，IP 封禁至少 3600 秒；读取 Retry-After（保护上限一年），已有冷却只延长、不缩短，后续被跳过的域不能把多日冷却重置为 120 秒。封禁不继续探测。网络失败与认证失败分开显示，API 不转发交易所原始错误正文。

网络请求期间不持有账户行锁。写入时重新按工作空间、归档状态与 credential_version 校验；密钥轮换或归档会清理旧快照，迟到结果丢弃。新结果已提交时，较早启动的旧同步不能覆盖它。Redis 解锁比较 token，不能删除其他请求的新锁。

审计仅记录账户、操作者、请求编号、凭据版本、结果和域错误码，不记录余额/持仓明细。HTTPX INFO 会包含签名 query，因此集中禁用 httpx/httpcore wire 日志；不启用请求体/认证头调试输出。

私有客户端 trust_env=False；只使用单独的 TRADEORBIT_PRIVATE_PROXY_URL，不继承公开行情代理。代理地址由服务端配置，不能从页面传入。公开采集 worker 不注入会话签名/凭据加密密钥或私有代理；交易锁继续由配置校验强制保持关闭。

本次只读边界复核不代替独立生产安全审计。

## 6. 核对资料与差异

2026-10-31 实际读取官方资料，并参考本地 CCXT 4.5.91 的对应字段实现；下载目录不作为运行依赖。本增量使用受控原生 GET，未引入整个 SDK。Bitget 旧 /api-doc 路径已转到新文档，不能把重定向到介绍页误当作端点契约。

- [Binance 官方 Spot REST 源码](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md)：账户、签名和时间；开发者站部分页面返回 202，衍生品细节同时参照官方文档与已下载实现，仍需实际账户验证。
- [Binance USDⓈ-M 账户 V3](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Information-V3)；[持仓 V3](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Position-Information-V3)。
- [Bitget Quick Start](https://www.bitget.com/docs/uta/quick-start)：HMAC、时间单位、域名、DEMO header。
- [Bitget 账户资产](https://www.bitget.com/docs/catalog/account/assets-balance)；[账户设置](https://www.bitget.com/docs/catalog/account/account-settings)；[经典持仓](https://www.bitget.com/docs/catalog/classic-contract-position/classic-contract-position)。
- [OKX 官方 V5](https://www.okx.com/docs-v5/en/)：认证、账户配置、余额、持仓、DEMO 和区域域名。

## 7. 验收记录

VALIDATION_STATUS: PASSED_INCREMENTAL

IS_PASS: YES（仅 E02-M2.1 手动只读增量；不代表 M2/E02 全部完成、实账联调或生产安全审计通过）。

验收日期：2026-10-31。证据为本地实际执行输出：

| 检查 | 结果 | 范围与证据 |
|---|---|---|
| 后端完整 pytest | PASS | 87 passed；含三所签名、只读路由、模式阻断、权限/CSRF/工作空间、快照持久化与失效、并发旧结果、精度和三天 Retry-After 不被缩短 |
| 后端 Ruff | PASS | check app tests 通过；format --check app tests：46 files already formatted |
| 后端 mypy | PASS | 40 source files，无错误 |
| 前端单元测试 | PASS | 20 项 / 5 文件；含迟到响应隔离、缓存重新挂载后过期、快照与单位展示 |
| 前端 lint / 类型 / 生产构建 | PASS | lint、vue-tsc --noEmit、Vite build；Docker 内生产构建再次通过 |
| 临时真实 PostgreSQL / Redis 验证 | PASS | 独立随机数据库 upgrade/check/downgrade/upgrade、角色、加密和并发凭据；结束后删除测试库，未向应用库写测试账户；未重启 db/cache |
| 本地镜像与迁移 | PASS | backend/frontend 构建成功；应用库 alembic current = 0003_account_read_state (head)，migrate 退出 0 |
| 本地服务 | PASS | backend、frontend、worker、market-worker、db、cache 六服务 healthy；ready 的 database/schema/redis 均 READY |
| 入口与认证冒烟 | PASS | /accounts HTTP 200；匿名读取账户/快照均 401；live.stage=E02_PRIVATE_READ_MANUAL，trading_enabled=false |
| 交付一致性 | PASS | git diff --check、相对文档链接检查通过；本地 .env 不在 Git 跟踪中 |
| 新账户快照页浏览器视觉/端到端 | NOT_RUN | 本轮没有浏览器自动化或截图验收，HTTP 200 仅表示入口可达 |
| 真实交易所私有账户 | NOT_RUN | 未使用用户真实凭据，不把离线 fixture 当作实账证据 |

本轮未修改依赖版本；M1 记录的开发工具全量审计 16 项中危仍为 DEP-01 待办，本轮未重新审计。没有下单、转账、提币或外部通知；没有自动提交或推送 Git。

离线测试使用测试专用凭据和 httpx.MockTransport；不读取用户密钥。真实私有账户联调为 NOT_RUN，不能用 fixture 通过代替实际 API 权限、IP、地区、模拟环境和字段核验。

## 8. 下一步与回退

M2.2：私有流引导/重连、后台定时快照、周期对账与缺失覆盖；M3：去重 NAV、估值缺口、历史净值、资金流水及风险告警。完成这些之前，页面只能称为手动快照。

回退前停止新 API，再用同版本 Alembic downgrade 0002_market_watchlist；这只删除新增快照表，不删除原账户、凭据和审计。正常回退优先保留表并切回上一版代码。不要执行 down -v，不要重新生成或覆盖现有 .env。
