# 阶段四生产部署

生产模式将业务数据、Checkpoint、限流和知识库分别放入 PostgreSQL、LangGraph PostgresSaver、Redis、S3 兼容对象存储及 pgvector。SQLite、Chroma 和本地知识目录只保留为单机开发模式。

## 初始化顺序

1. 准备 PostgreSQL 17（包含 pgvector 扩展）、Redis 和 S3 兼容对象存储，并创建 `lifepilot-knowledge` 私有 Bucket。
2. 复制 `.env.example` 中的生产配置，使用独立高强度密码。不要把 `.env` 提交到 Git。
3. 执行业务迁移和 Checkpoint 一次性初始化：

   ```powershell
   python scripts/initialize_production_database.py
   ```

4. 停止旧实例写入并备份 `lifepilot.db`、`checkpoints.db` 和 `knowledge_base`。
5. 迁移业务数据和 Checkpoint；知识库应重新解析、重新向量化，不复制 Chroma 文件：

   ```powershell
   python scripts/migrate_to_production.py `
     --sqlite data/lifepilot.db `
     --checkpoints data/checkpoints.db `
     --include-knowledge `
     --knowledge-directory knowledge_base
   ```

6. 启动至少一个知识 Worker，再启动 API：

   ```powershell
   celery -A app.tasks.celery_app.celery_app worker -Q knowledge --loglevel=INFO
   uvicorn app.api.server:app --host 0.0.0.0 --port 8000
   ```

## 切换与回滚

- 迁移工具的业务写入和 Checkpoint 写入均可重复执行；知识任务按文档 ID 重建向量。
- 切换前核对各业务表行数、用户登录、会话读取、知识检索和管理员用量汇总。
- 回滚时先停止新实例写入，再恢复旧 SQLite 文件和旧环境变量。新系统切换后产生的数据不会自动反向同步到 SQLite。
- PostgreSQL、Redis 和对象存储应分别配置持久化备份。对象存储 Bucket 必须保持私有，并启用服务端加密。

## 本地编排文件

`compose.production.yml` 仅提供开发/验收基础设施，不包含真实密码。首次启动会下载容器镜像；执行前需要单独审批。
