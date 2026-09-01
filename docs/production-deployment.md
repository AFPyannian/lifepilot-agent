# 阶段四生产部署

生产模式使用 PostgreSQL/pgvector 保存业务数据和向量，使用独立的 LangGraph PostgresSaver 表保存 Checkpoint，Redis 提供共享限流、Celery Broker 和任务结果，MinIO 保存知识源文件。SQLite、Chroma 和本地知识目录只用于单机开发模式。

## 容器拓扑

`compose.production.yml` 会启动以下服务：

- `postgres`：PostgreSQL 17 与 pgvector，宿主机仅监听 `127.0.0.1:5432`。
- `redis`：限流和 Celery，宿主机仅监听 `127.0.0.1:6379`。
- `minio` / `minio-init`：对象存储及私有 Bucket 初始化，控制台为 `127.0.0.1:9001`。
- `database-init`：执行 Alembic 迁移和 LangGraph Checkpoint 初始化后退出。
- `api`：两个 Uvicorn Worker，地址为 `http://127.0.0.1:8000`。
- `worker`：消费 `knowledge` 队列，后台解析并向量化知识文档。
- `frontend`：Streamlit，地址为 `http://127.0.0.1:8501`。

服务数据保存在 Docker 命名卷中；项目的 `models` 目录以只读方式挂载进应用容器。所有对宿主机开放的端口都只绑定回环地址，若要跨设备访问，应在前方配置 HTTPS 反向代理，不要直接改成 `0.0.0.0` 暴露数据库或管理端口。

## 首次配置

1. 确认 Docker Desktop 使用 Linux containers，并确认项目存在 `models/bge-small-zh-v1.5`。
2. 将 `.env.example` 复制为 `.env`，替换以下值：

   - `POSTGRES_PASSWORD`、`REDIS_PASSWORD`、`MINIO_ROOT_PASSWORD`：使用不同的高强度 URL-safe 密码，只使用字母、数字、`-`、`_`，避免连接 URL 转义问题。
   - `MINIO_ROOT_USER`：对象存储管理员名。
   - `DEEPSEEK_API_KEY`：启用平台模型时必须填写；如仅使用 BYOK，应按配置文档关闭平台模型并配置凭据主密钥环。
   - `PROVIDER_CREDENTIAL_MASTER_KEYS`：启用 BYOK 时必须在数据库之外单独备份。
   - `REGISTRATION_MODE`：保持 `closed`，或在管理员创建邀请码后改为 `invite`。

3. 不要填写 Compose 已在容器内部覆盖的 `DATABASE_URL`、`CHECKPOINT_DATABASE_URL`、`REDIS_URL`、Celery URL 和对象存储访问地址。不要把 `.env` 提交到 Git。

也可以仅为当前缺失的基础设施配置生成随机值；脚本不会覆盖已有值，也不会显示密钥：

```powershell
.\scripts\configure_production_env.ps1
```

可使用以下脚本只为缺失的基础设施变量生成密码；脚本不会覆盖已有值，也不会输出密码：

```powershell
.\scripts\configure_production_env.ps1
```

静态检查编排文件不会下载镜像：

```powershell
docker compose --env-file .env -f compose.production.yml config --quiet
```

## 启动、检查与停止

首次构建和启动会联网下载镜像及 Python 包：

```powershell
docker compose --env-file .env -f compose.production.yml up -d --build
docker compose --env-file .env -f compose.production.yml ps
```

检查应用和依赖：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/v1/ready
docker compose --env-file .env -f compose.production.yml exec worker `
  celery -A app.tasks.celery_app.celery_app inspect ping
```

查看日志或停止服务：

```powershell
docker compose --env-file .env -f compose.production.yml logs --tail 200 api worker
docker compose --env-file .env -f compose.production.yml down
```

`down` 不删除数据卷。只有在确认不再需要数据并已经备份后，才可显式执行 `down --volumes`。

## 旧数据迁移

1. 停止旧实例写入，并备份 `data/lifepilot.db`、`data/checkpoints.db` 和 `knowledge_base`。
2. 保持新容器运行，进入 API 容器执行可重复迁移；知识库会重新解析和向量化，不复制 Chroma 文件：

   ```powershell
   docker compose --env-file .env -f compose.production.yml exec api `
     python scripts/migrate_to_production.py `
       --sqlite data/lifepilot.db `
       --checkpoints data/checkpoints.db `
       --include-knowledge `
       --knowledge-directory knowledge_base
   ```

   如需从宿主机迁移，必须先把旧数据目录以只读卷挂载进容器；默认生产编排不会挂载本地 `data` 或 `knowledge_base`，防止误用开发数据。

3. 核对各业务表行数、用户登录、会话读取、知识检索、后台任务和管理员用量/配额页面后再切换流量。

## 真实基础设施集成测试

集成测试默认跳过，避免在普通测试中误连生产服务。对本机验收栈设置下列环境变量后运行：

```powershell
$env:RUN_PRODUCTION_INTEGRATION_TESTS = "true"
$env:DATABASE_URL = "postgresql+psycopg://lifepilot:<密码>@127.0.0.1:5432/lifepilot"
$env:CHECKPOINT_DATABASE_URL = "postgresql://lifepilot:<密码>@127.0.0.1:5432/lifepilot"
$env:REDIS_URL = "redis://:<密码>@127.0.0.1:6379/0"
$env:CELERY_BROKER_URL = "redis://:<密码>@127.0.0.1:6379/1"
$env:CELERY_RESULT_BACKEND = "redis://:<密码>@127.0.0.1:6379/2"
$env:OBJECT_STORAGE_ENDPOINT_URL = "http://127.0.0.1:9000"
$env:OBJECT_STORAGE_ACCESS_KEY = "<MINIO_ROOT_USER>"
$env:OBJECT_STORAGE_SECRET_KEY = "<MINIO_ROOT_PASSWORD>"
python -m pytest tests/test_phase4_integration.py -v
```

测试会创建带随机标识的临时用户、Redis Key 和 MinIO 对象，并在结束时清理持久对象。

## 备份与回滚

- PostgreSQL、Redis 和 MinIO 数据目录应分别配置备份；MinIO Bucket 必须保持私有。
- 切换失败时先停止新实例写入，再恢复旧 SQLite 文件和旧环境变量。生产切换后新增的数据不会自动反向同步到 SQLite。
- 月请求配额在模型调用前原子预占；失败调用也计入请求数。Token 只能在供应商成功响应后结算，因此一次响应可能略微越过 Token 上限，后续调用会被拒绝。
