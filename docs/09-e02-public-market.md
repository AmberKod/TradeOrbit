# E02-M1 公开行情工作台：功能、实现与验收

日期：2026-10-31 / 工程版本：0.2.0 / E02 总体状态：IN_PROGRESS。

本次交付先完成公开行情闭环。它不代表 E02 的账户资产同步已经完成，也不授权真实订单、转账、提币或外部消息发送。最终验收结果在本文第 9 节记录。

## 1. 功能与范围

| 模块 | 已实现行为 |
|---|---|
| 产品目录 | Binance、Bitget、OKX 的 USDT 现货及 USDT 线性永续，过滤非交易状态和不支持产品；可按交易所、市场与币种搜索 |
| 行情自选 | 按工作空间保存，ADMIN/TRADER 添加移除，VIEWER 只读；去重并限制每工作空间 40 项 |
| 实时报价 | 公开 WebSocket 最新价、买一卖一、24h 高低价、涨跌幅与成交量；缺失字段保留 null/— |
| 数据状态 | 六组独立连接、产品规格新鲜度、WS/REST 来源、报价年龄、断线和过期标记 |
| 详情 | 每 5 秒请求 REST 快照；最近 120 根 1m K 线、买卖各 5 档、最近 20 笔成交 |
| 页面 | 中文行情工作台、桌面与窄屏、自选持久化、选中交易对详情；原首页与账户功能继续保留 |
| 运维 | 独立 market-worker、心跳、连接退避、REST 降级、租约、显式代理配置、迁移和测试 |

边界：K 线、盘口、最近成交是明确标注的 REST 快照，不是本地维护的实时增量盘口。当前没有资金费率、OI、爆仓流、价格/爆量告警、资产 NAV、持仓 PNL、交易执行或策略运行。页面不自动插入假行情或示例自选。

公开行情使用交易所主站的公共市场数据，与账户配置中的 DEMO/LIVE、Bitget CLASSIC/UTA 等私有模式独立。公开报价可用不等于用户账户通过验证。现有账户能力继续是 NOT_VERIFIED。

## 2. 架构与主要文件

~~~mermaid
flowchart LR
 EX[三所公开 REST / WebSocket] --> MW[独立 market-worker]
 DB[(PostgreSQL 自选)] --> MW
 MW --> RC[(Redis 产品 / 报价 / 状态 / PubSub)]
 DB --> API[FastAPI 会话鉴权]
 RC --> API
 API -->|同源会话 WebSocket| UI[Vue 行情工作台]
 API -->|有界 REST 快照请求| EX
 UI -->|添加 / 移除 / 详情| API
~~~

- backend/app/exchanges/：统一 Instrument/Ticker、三所公开适配器、HTTP 错误及盘口/成交/K 线归一化。
- backend/app/market/worker.py：公开行情采集、产品目录刷新、订阅协调、连接状态和 Redis 写入；没有读取交易所凭据表或下单路径。
- backend/app/market/service.py：工作空间快照、自选元数据、REST 详情缓存与并发保护。
- backend/app/api/market.py、backend/app/market/stream.py：登录鉴权、角色、自选审计、精确 Origin 校验及推送协议。
- backend/app/models/market.py、backend/alembic/versions/0002_market_watchlist.py：自选持久化。
- frontend/src/stores/market.ts、frontend/src/views/MarketView.vue、frontend/src/components/CandleChart.vue：推送状态、页面与 SVG K 线。
- compose.yaml、frontend/nginx.conf、frontend/vite.config.ts：独立采集进程与同源 WebSocket 转发。

Compose 只向 market-worker 注入数据库、Redis 和可选公开代理地址，不向它注入会话签名密钥或凭据解密密钥。API 继续承载 E01 账户配置与加密功能，但公开行情服务不查询这些凭据。

## 3. 六组官方接入与数据口径

以下固定官方路由在 2026-10-31 做过真实公开 REST 与 WebSocket 探测；地区、网络策略或交易所后续变更仍可能影响可达性。不能据此推断所有私有地区端点都可用。

| 交易所 / 市场 | REST 根路径 | WebSocket / 订阅 |
|---|---|---|
| Binance 现货 | https://data-api.binance.vision/api/v3 | wss://data-stream.binance.vision/stream?streams=btcusdt@ticker；多交易对用 / 分隔流名 |
| Binance USDT 永续 | https://fapi.binance.com/fapi/v1 | wss://fstream.binance.com/market/stream?streams=btcusdt@ticker |
| Bitget 现货 | https://api.bitget.com/api/v2/spot | wss://ws.bitget.com/v2/ws/public；op=subscribe，instType=SPOT，channel=ticker |
| Bitget USDT 永续 | https://api.bitget.com/api/v2/mix | 同上；instType=USDT-FUTURES，channel=ticker |
| OKX 现货 | https://www.okx.com/api/v5 | wss://ws.okx.com/ws/v5/public；channel=tickers，instId=BTC-USDT |
| OKX USDT 永续 | 同上 | 同上；instId=BTC-USDT-SWAP |

### 产品与快照端点

- Binance：exchangeInfo、ticker/24hr、depth(limit=5)、klines(interval=1m, limit=120)、trades(limit=20)。现货与期货使用各自的根路径，永续还校验 PERPETUAL / USDT / TRADING。
- Bitget 现货：public/symbols；market/tickers、market/orderbook(type=step0)、market/candles(granularity=1min)、market/fills。
- Bitget 永续：market/contracts、market/tickers、market/merge-depth(precision=scale0)、market/candles(granularity=1m)、market/fills；productType=USDT-FUTURES。当前采用 v2 公开市场接口，不据此声明私有 UTA v3 已接入。
- OKX：public/instruments(instType=SPOT/SWAP)、market/tickers、market/books(sz=5)、market/candles(bar=1m, limit=120)、market/trades(limit=20)；永续过滤 state=live、ctType=linear、settleCcy=USDT。

### 归一化约定

- 唯一标识为 exchange:market_type:native_symbol，例如 binance:SPOT:BTCUSDT 与 binance:USDT_PERP:BTCUSDT。不能只用 BTCUSDT 区分市场。
- 服务端金额/数量用 Decimal；JSON 价格、数量、涨跌幅为十进制字符串。浏览器 Number 仅用于显示、画图，不用于订单或账务。
- OKX 永续盘口与成交的原始数量是张数，统一基础币数量 = 原始张数 × ctVal × ctMult；规格同时校验 ctValCcy。接口保留 native_quantity 与原始单位，页面说明换算依据。
- OKX 现货 vol24h 为基础币、volCcy24h 为计价币；永续 volCcy24h 为基础币。永续 USDT 成交额没有准确原字段时返回 null，不用最新价乘基础币量伪造历史成交额。
- Binance 使用原生 24h 涨跌百分比；Bitget/OKX 优先用 last/open24h 计算，Bitget 比率回退时乘 100。
- 成交方向为主动买/主动卖；Binance isBuyerMaker=true 对应主动卖。未知方向保留 UNKNOWN。
- K 线按开盘时间升序去重，拒绝非有限数及不合理 OHLC；OKX 保留原生确认标志，其他来源不推断已收盘。
- 盘口排序、剔除无效档位并拒绝空盘口或买一不低于卖一的异常快照；不以零价补齐。

## 4. 数据持久化与接口

迁移版本为 0002_market_watchlist，前置为 0001_foundation。新增 market_watchlist：UUID 主键、workspace_id、created_by、instrument_key、created_at；唯一约束 (workspace_id, instrument_key)，按工作空间建索引。新增表不改写 E01 用户、账户或凭据。降级会删除自选表，仅适用于明确允许丢失该表数据的回退场景。

Redis 的 tradeorbit:market: 前缀维护六组产品目录与来源状态、每交易对报价、详情缓存、PubSub 和采集进程心跳。自选权威来源是 PostgreSQL。Redis 里不存交易所明文密钥。

| 接口（均以 /api/v1 为前缀） | 权限 / 行为 |
|---|---|
| GET /market/instruments | 已登录；exchange、market_type、search、limit（最大 100）；目录不是实时远端搜索 |
| GET /market/watchlist | 已登录；仅当前工作空间的自选、元数据和行情；含六组公开来源及 worker_alive |
| POST /market/watchlist | ADMIN/TRADER + Origin + CSRF；校验近期目录；锁工作空间行控制并发上限；重复添加返回 created=false |
| DELETE /market/watchlist/{uuid} | ADMIN/TRADER + Origin + CSRF；仅删除当前空间条目，跨空间 UUID 返回 404 |
| GET /market/detail?key=... | 已登录；只允许已同步产品，返回独立的 book/candles/trades 组件和 REST_SNAPSHOT 标记 |
| WS /market/stream | HttpOnly 会话 Cookie + 精确 Origin；不使用 URL token 或 localStorage token |

增加、删除自选记录元数据审计。数据库提交后 PubSub 通知是尽力发送；通知暂时失败不把已提交操作误报失败，5 秒周期快照补偿。

## 5. 推送、健康与过期处理

帧字段：type、schema_version=1、connection_id、sequence、server_time、data。sequence 仅在当前 connection_id 内单调递增，重连会重置。type 为 snapshot / tickers / heartbeat；tickers.data.items 为合并批次。

- 建连先校验 Origin 与会话，发送当前空间 snapshot；仅把自选 key 的 ticker 发给该连接。
- 增量按 250ms 合并；完整快照每 5 秒，心跳每 2 秒；每 15 秒重新检查会话与成员资格，注销会话后关闭连接。
- 浏览器只接受单调序号和当前连接帧，丢弃旧报价时间戳；序号缺口请求 resync。HTTP 刷新不覆盖浏览器已经收到的较新报价。
- 前端用服务器时间校准本地显示。报价年龄结合 source_ts（若有）和 received_at；超过 15 秒、浏览器推送断线或采集心跳消失时标记过期。心跳不刷新价格的时间。
- 来源状态为 WAITING、IDLE、CONNECTING、LIVE、DEGRADED、UNAVAILABLE；只有收到有效 WS 报价后才进入 LIVE。IDLE 表示目录可用但没有该组自选订阅。
- 采集端 45 秒没有有效 WS 报价则重连；退避为指数 1–30 秒并带抖动；Bitget/OKX 使用文本 ping/pong，Binance 使用协议 ping/pong。
- WS 不可用时每 10 秒使用公开 REST ticker 降级，明确显示 REST；429 尊重有界 Retry-After。错误日志只保留代码、交易所与市场，不记录代理地址或秘密。
- 采集端比较已有报价源时间，进程重启时也读取缓存避免旧事件覆盖新报价。
- 产品目录启动时先恢复 Redis 中两小时内的有效规格，但不改写原更新时间；随后从官方重新获取并每小时刷新。新请求暂时失败不会阻止已有有效目录的行情订阅。过期目录不用于冷启动恢复，失败按退避重试，超过两小时拒绝新自选。
- API readiness 检查数据库、Redis、迁移版本。采集心跳只证明进程在工作，不等于每个交易所行情可用；交易所失败不会触发无意义的容器重启风暴。

## 6. 有界资源与快照降级

- 单个工作空间最多 40 项；整个采集进程每个交易所/市场最多 80 个订阅，超过时按排序选择前 80，界面显示 requested/subscribed 缺口。该默认预算适用于个人/可信小团队，不能当作无限多租户服务。
- 采集进程用 Redis 租约避免重复运行，5 秒协调一次数据库自选。行情报价缓存保留 300 秒，超过前端新鲜度窗口即显示过期，不因仍有缓存就宣称实时。
- 详情刷新缓存 5 秒、保留 300 秒；同交易对 Redis NX 锁 30 秒并按持有者比较删除，避免误删他人的锁。
- API 实例最多并行 2 个详情快照请求，等候最多 1 秒，整体快照超时 15 秒。忙时返回 MARKET_BUSY，不积压无限队列。
- book/candles/trades 分别返回 FRESH / STALE / UNAVAILABLE、received_at、error。某一组件失败时可保留先前有效组件，但必须标记 STALE；全部失效时重试冷却 30 秒。
- UI 按组件时间显示过期快照；切换交易对时取消旧请求并清空旧详情，避免把另一个产品的盘口贴到当前标题下。
- 本增量没有分布式多实例扇出优化、历史行情存储、交易所完整序列盘口、订单路由、公开生产托管或账户资产账务能力。

## 7. 本地启动与网络

已有 .env 和管理员时，不重复初始化环境或管理员：

~~~powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
~~~

打开 http://localhost:18080/market ，也可以从左侧“行情工作台”进入。先选择交易所/市场，再从真实产品目录添加 BTC、ETH 或其他产品。自选会持久化，空列表不会自动发起额外订阅。

国内或受限网络需显式配置可达的官方网络出口。可选 TRADEORBIT_PUBLIC_PROXY_URL 仅供公开 REST/WS 客户端使用；HTTPX 关闭环境自动代理，避免 Windows 系统绕过列表中的异常 IPv6 规则导致初始化失败。保持 TLS 校验，不使用未经确认的镜像。

Docker 访问本机代理使用 http://host.docker.internal:实际端口，不能使用容器自己的 127.0.0.1。宿主机运行 API 时对应地址应为 http://127.0.0.1:实际端口；用当前终端环境变量覆盖配置，不能照抄示例端口。代理服务必须实际运行并允许容器访问。不要输出完整 .env 或展开的 docker compose config。

排查命令：docker compose logs --tail 100 market-worker backend；产品目录未就绪时先看该组来源错误，连接上浏览器 WS 不代表上游已连接。重试不会替代正确的网络、地区和产品权限配置。

## 8. 验证命令与边界

~~~powershell
uv run --directory backend ruff check .
uv run --directory backend ruff format --check .
uv run --directory backend mypy
uv run --directory backend pytest -q
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test:unit
npm --prefix frontend run build
npm --prefix frontend audit
~~~

backend/tests/test_market.py 的回放数据仅用于测试，覆盖数值拒绝、张数换算、K 线去重排序、六组原生 ticker、限流、鉴权/CSRF、角色、自选去重与容量、工作空间隔离、快照缓存降级、锁保护、WS 来源与会话注销、重启报价排序、迟到 REST 成功/失败竞态、冷启动目录恢复及过期缓存拒绝。frontend/src/stores/market.test.ts 覆盖心跳不刷新报价、重复/旧帧、快照竞态、重连和退出清理。

实际公开行情探测不需要私有密钥。页面验收用独立验证工作空间和随机临时身份，结束后清理，不使用用户密码，不访问用户的交易所密钥，也不触发订单。

## 9. 本轮验收结果

本轮按“部分流程 / 增量实现 → QA → 全局一致性检查”交付。IS_PASS: YES（仅 E02-M1 功能范围）；QA 路由：NoOne。E02 总体仍为 IN_PROGRESS，生产安全发布不在本轮通过范围内。

| 检查 | 结果与证据 |
|---|---|
| 后端单元与回归 | 50 passed；含 E01 21 项基线及公开行情、权限、缓存、竞态和目录恢复测试 |
| 后端静态检查 | Ruff check、Ruff format --check、mypy（35 个源码文件）、uv lock --check 均通过 |
| 前端 | 12 passed；lint、Vue/TypeScript 类型检查与生产构建通过 |
| 官方公开端点 | 三所 × 现货/USDT 永续：真实产品目录、ticker、盘口、K 线、成交解析及 WS 订阅均成功 |
| 容器到浏览器链路 | market-worker → Redis → API → Nginx WS → 客户端，六组收到新鲜 WS 报价，帧连接 ID/序号检查通过 |
| 真实详情 | 六组各 book/candles/trades 共 18 个组件 FRESH；每组 5+5 档、120 根 K 线、20 笔成交 |
| 浏览器交互 | 真实 UI 添加 ETH、刷新后仍保留、移除、跨交易所/市场切换；最终独立空间自选恢复为六个 BTC 产品 |
| 视觉与窄屏 | 桌面 1440px、窄屏 390px；文档宽度不超视口、无脚本异常；K 线/盘口/成交均有真实内容；六组状态可正确恢复为 LIVE |
| 数据库迁移 | 独立临时 PostgreSQL：upgrade/check/downgrade/upgrade/check 通过；应用库仅升级新增表 |
| 基础工程回归 | 真实 PostgreSQL/Redis 再次验证引导、登录、角色、测试凭据加密流程和并发凭据版本；独立验证数据库已清理 |
| 现有用户数据 | 页面验收创建的独立验证身份和空间已清理，前后用户数量一致；没有读取用户密码或交易所密钥 |
| 本地运行 | API、前端、PostgreSQL、Redis、心跳 worker、market-worker 六个长期服务均 healthy；端口继续仅绑定回环 |
| 依赖审计 | 运行依赖为 0；全量仍有 16 项中危开发工具提示，见 DEP-01，未冒充已修复 |

验收中发现并修复了两个恢复问题：迟到 REST 请求覆盖已恢复 WS 状态，以及重启时目录请求失败却没有恢复有效缓存。两者都补充了确定性测试；后续真实六组链路与页面复验通过。

本地证据图片保存在忽略目录 .local/e02-market-desktop.png 与 .local/e02-market-mobile.png。它们使用已清理的独立验证身份，不属于生产前端资源。源码与本文均不包含用户秘密。



### 依赖审计未完成项 DEP-01

2026-10-31 从 npm 官方审计取得：运行依赖 npm audit --omit=dev 为 0；全量审计为 16 项 moderate、0 high/critical，主要涉及开发工具的 minimatch/glob 及其上游 lint/格式工具依赖链。全量审计不为零，该项尚未修复。

最终 Nginx 运行镜像只拷贝构建后的静态文件，不包含 Node 构建工具链。仍需单独完成兼容升级与完整回归；本轮未使用 npm audit fix --force 的跨主版本回退建议，也未全局覆盖不兼容的 minimatch 主版本。当前功能验收不等于生产安全发布验收。

## 10. 下一增量

E02-M2：三所私有只读能力探测、地区/账户模式/环境识别、余额/持仓同步与对账、权益去重和覆盖范围；之后补充 NAV 历史、资金费率、OI、爆仓源与完整盘口能力。没有凭据或对应环境时只做脱敏回放并明确未联调，不把公开行情的成功当作私有接入成功。
