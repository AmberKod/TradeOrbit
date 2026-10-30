# 基础设施

根目录 `compose.yaml` 是本地启动入口：PostgreSQL 17、Redis 7.4、显式迁移任务、API、心跳 worker、Nginx 前端。构建文件分别位于 backend、frontend；Nginx 反向代理配置位于 frontend/nginx.conf。

所有主机端口绑定 127.0.0.1，数据服务使用独立网络（本地调试需允许回环端口映射）；此配置是本地开发基线。公网部署需要 HTTPS、严格来源列表、Secure cookie、密钥托管、备份恢复与访问控制，不能直接改成 0.0.0.0 后作为生产环境。

迁移先于 API/worker 启动；API lifespan 不自动修改数据库结构。数据库和 Redis 使用命名卷。`docker compose down` 保留数据，`down -v` 会删除数据，勿用于日常停止。
