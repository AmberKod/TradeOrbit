# Worker 边界

E01 入口位于 `backend/app/worker.py`，与 API 共用构建镜像，通过独立进程运行。当前仅维护 Redis 中 30 秒 TTL 的基础心跳，每 10 秒刷新；可用 `python -m app.worker --check` 检查。

当前不访问交易所、不读取账户密钥、不运行策略、不执行订单。E02 在独立任务中接入行情与账户同步；E05 再增加隔离策略进程。后续 worker 按任务拆分镜像/权限，禁止把交易执行直接挂在 API 请求中。
