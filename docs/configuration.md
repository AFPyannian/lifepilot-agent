# 配置说明

## 1. 配置加载规则

LifePilot 使用 Pydantic Settings 读取项目根目录的 `.env` 和进程环境变量。字段名不区分大小写，环境变量优先级高于 `.env`。

创建本地配置：

```powershell
Copy-Item .env.example .env
```

`.env` 包含真实密钥和本地路径，已被 `.gitignore` 排除，不得提交。`.env.example` 只保存安全的默认值和空占位符。

## 2. 默认平台模型配置

```env
DEEPSEEK_API_KEY=your-deepseek-api-key
```

知识库导入、检索和 RAG 评估还要求本地 Embedding 模型存在于默认路径；不使用知识库时，后端可以在没有该模型的情况下启动：

```text
models/bge-small-zh-v1.5
```

下载命令：

```powershell
python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='BAAI/bge-small-zh-v1.5', local_dir='models/bge-small-zh-v1.5')"
```

## 3. 模型配置

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DEEPSEEK_API_KEY` | 条件必填 | 无 | 启用平台模型时使用的服务端 DeepSeek Key |
| `DEEPSEEK_MODEL` | 否 | `deepseek-v4-flash` | 聊天模型名称 |
| `DEEPSEEK_TIMEOUT_SECONDS` | 否 | `60` | 单次模型请求超时秒数，必须大于 0 |
| `DEEPSEEK_MAX_RETRIES` | 否 | `2` | 模型客户端最大重试次数，范围 0～10 |
| `CREDENTIAL_VALIDATION_TIMEOUT_SECONDS` | 否 | `15` | 用户 Key 受控验证请求的超时秒数 |
| `BYOK_ENABLED` | 否 | `false` | 是否允许登录用户保存自己的 DeepSeek Key |
| `PLATFORM_MODEL_ENABLED` | 否 | `true` | 是否允许使用服务端统一配置的 Key |
| `DEFAULT_MODEL_MODE` | 否 | `PLATFORM` | 新聊天请求的默认模型模式 |
| `PROVIDER_CREDENTIAL_MASTER_KEYS` | BYOK 启用时 | 空 | JSON 格式的服务端主密钥环 |
| `PROVIDER_CREDENTIAL_ACTIVE_KEY_VERSION` | BYOK 启用时 | `v1` | 新凭据使用的主密钥版本 |

模型重试只覆盖模型客户端请求，不会自动重放完整 Agent 工作流，以避免重复执行写入类工具。

### 用户自带 DeepSeek Key

生成一份32字节主密钥：

```powershell
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

启用 BYOK：

```env
BYOK_ENABLED=true
PROVIDER_CREDENTIAL_MASTER_KEYS={"v1":"替换为生成结果"}
PROVIDER_CREDENTIAL_ACTIVE_KEY_VERSION=v1
```

登录用户在 Streamlit 的“模型设置”中提交 Key。后端先发起不进入 LangSmith
回调链的最小验证请求，验证成功后才使用 AES-256-GCM 写入数据库。界面和 API
只返回末四位掩码，不提供原始 Key 读取或导出接口。生产环境必须使用 HTTPS，
并将主密钥放在数据库之外的环境变量、Vault 或 KMS 中。

轮换主密钥时，先同时配置旧版本和新版本，并将活动版本切到新版本：

```env
PROVIDER_CREDENTIAL_MASTER_KEYS={"v1":"旧密钥","v2":"新密钥"}
PROVIDER_CREDENTIAL_ACTIVE_KEY_VERSION=v2
```

停止写入服务后执行：

```powershell
python -m scripts.rewrap_provider_credentials --from-version v1
```

确认数据库中不存在 `v1` 记录后才能移除旧主密钥。数据库备份和主密钥必须分开保管。

## 4. API 认证与限流

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `AUTH_SESSION_TTL_HOURS` | 否 | `168` | Session 有效期小时数，范围 1～2160 |
| `AUTH_SESSION_TOUCH_INTERVAL_SECONDS` | 否 | `300` | Session 最近使用时间的最小更新间隔 |
| `AUTH_LOGIN_MAX_FAILURES` | 否 | `5` | 登录窗口内允许的失败次数 |
| `AUTH_LOGIN_WINDOW_SECONDS` | 否 | `900` | 登录失败计数窗口秒数 |
| `REGISTRATION_MODE` | 否 | `closed` | `closed` 关闭注册；`invite` 启用一次性邀请码注册 |
| `AUTH_REGISTRATION_MAX_FAILURES` | 否 | `10` | 注册窗口内允许的失败次数 |
| `AUTH_REGISTRATION_WINDOW_SECONDS` | 否 | `900` | 注册失败计数窗口秒数 |
| `AUTH_INVITATION_MAX_TTL_HOURS` | 否 | `720` | 管理员可设置的邀请码最长有效期 |
| `API_RATE_LIMIT_ENABLED` | 否 | `true` | 是否启用业务接口限流 |
| `API_RATE_LIMIT_REQUESTS` | 否 | `60` | 一个时间窗口内允许的请求数 |
| `API_RATE_LIMIT_WINDOW_SECONDS` | 否 | `60` | 限流窗口秒数 |

账号认证始终启用。首次启动前创建管理员账号，密码使用 Argon2id 哈希后保存：

```powershell
python -m scripts.user_admin create --username admin --role admin
```

首次管理员必须通过 CLI 创建。项目默认不开放注册；如需允许用户自行设置密码，可配置：

```env
REGISTRATION_MODE=invite
```

重启后端后，管理员可在 Streamlit 中生成一次性邀请码。邀请码原文只展示一次，数据库只保存 SHA-256 摘要；注册创建的账号固定为 `user / active`。

管理员仍可在本机直接创建用户、禁用或启用账号，以及重置密码：

```powershell
python -m scripts.user_admin create --username alice --role user
python -m scripts.user_admin status --username alice --status disabled
python -m scripts.user_admin status --username alice --status active
python -m scripts.user_admin reset-password --username alice
```

### 平台模型授权

账号启用不等于自动获得平台模型。升级到本阶段时，数据库中既有的启用账号会获得一次性 `migration` 授权；之后注册的账号需要配置 BYOK，或由本地管理员发放 `model.platform`：

```powershell
python -m scripts.entitlement_admin list --username alice
python -m scripts.entitlement_admin grant --username alice --granted-by admin --capability model.platform --expires-in-days 30
python -m scripts.entitlement_admin revoke --entitlement-id <授权ID>
```

省略 `--expires-in-days` 表示不自动过期。授权人必须是数据库中启用状态的管理员。

以下端点保持公开：

- `/api/v1/auth/login`
- `GET /api/v1/auth/registration`
- `POST /api/v1/auth/register`（仅邀请模式可成功注册）
- `/api/v1/health`
- `/api/v1/ready`
- `/docs`
- `/openapi.json`

登录成功后 API 返回一次原始 Session 令牌，客户端通过 `Authorization: Bearer <token>` 访问其他接口；数据库只保存令牌摘要。Streamlit 仅在当前浏览器 Session 中保存原始令牌，不写入 `.env`、Cookie 或磁盘。

登录失败限流按客户端 IP 和用户名摘要计数，业务限流按 Session 摘要计数。本地模式保存在进程内存中；生产模式使用 Redis 原子脚本跨 Worker 共享。

## 4.1 生产基础设施

`INFRASTRUCTURE_MODE=local` 保持 SQLite、Chroma、本地知识文件和进程内限流。切换为 `production` 后，连接类配置必须显式提供：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `INFRASTRUCTURE_MODE` | `local` | `local` 使用单机存储；`production` 使用共享基础设施 |
| `DATABASE_URL` | 空 | SQLAlchemy PostgreSQL 业务库连接串；生产模式必填 |
| `CHECKPOINT_DATABASE_URL` | 空 | LangGraph PostgresSaver 连接串；生产模式必填 |
| `DATABASE_POOL_SIZE` | `10` | SQLAlchemy 连接池常驻连接数 |
| `DATABASE_MAX_OVERFLOW` | `20` | 连接池允许临时增加的连接数 |
| `DATABASE_POOL_RECYCLE_SECONDS` | `1800` | 数据库连接回收秒数 |
| `REDIS_URL` | 空 | Redis 共享限流连接地址；生产模式必填 |
| `REDIS_KEY_PREFIX` | `lifepilot` | Redis 限流键前缀 |
| `OBJECT_STORAGE_ENDPOINT_URL` | 空 | S3 兼容端点；AWS S3 可留空 |
| `OBJECT_STORAGE_REGION` | `us-east-1` | 对象存储区域 |
| `OBJECT_STORAGE_BUCKET` | `lifepilot-knowledge` | 私有知识文件 Bucket |
| `OBJECT_STORAGE_ACCESS_KEY` | 空 | 对象存储访问 Key；生产模式必填 |
| `OBJECT_STORAGE_SECRET_KEY` | 空 | 对象存储 Secret；生产模式必填 |
| `OBJECT_STORAGE_SECURE` | `true` | 是否使用 HTTPS 访问对象存储 |
| `OBJECT_STORAGE_SSE` | `AES256` | 服务端加密模式；可选 `none` 或 `AES256` |
| `CELERY_BROKER_URL` | 空 | Celery Broker 地址；生产模式必填 |
| `KNOWLEDGE_WORKER_QUEUE` | `knowledge` | 知识库后台任务队列名；默认 Compose Worker 固定消费 `knowledge`，使用自定义值时需同步修改 Worker 命令 |
| `KNOWLEDGE_TASK_MAX_RETRIES` | `3` | 知识库后台任务最大重试次数 |
| `EMBEDDING_DIMENSION` | `512` | pgvector 向量维度；必须与数据库迁移和模型一致 |
| `THREAD_LOCK_WAIT_SECONDS` | `5` | 同一用户会话锁的最长等待秒数 |

使用 `compose.production.yml` 时还必须提供 `POSTGRES_PASSWORD`、
`REDIS_PASSWORD`、`MINIO_ROOT_USER` 和 `MINIO_ROOT_PASSWORD`。这些变量由
Compose 用于启动依赖服务并生成上表中的连接配置，不是 `Settings` 的直接字段。

业务数据库、Checkpoint 数据库、Redis 和对象存储会通过生产就绪检查持续探测。完整初始化、迁移、Worker 启动和回滚顺序见[生产部署](production-deployment.md)。

## 5. Agent 运行限制

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `AGENT_RECURSION_LIMIT` | `25` | 单次 LangGraph 运行允许的最大 supersteps，范围 5～100 |

这个值限制单次图运行中的节点执行次数，不限制会话中的用户消息总数。

## 6. 用户身份与会话

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LOCAL_CLI_OWNER_ID` | `local-user` | 仅供直接运行 CLI 时使用的本地身份 |
| `DEFAULT_THREAD_ID` | `main` | CLI 默认会话 ID |

Web/API 的用户 UUID 只来自服务端认证结果，不接受请求体或模型参数指定身份。Repository、Checkpoint、知识文件和 Chroma 元数据都使用该 UUID 隔离数据；`LOCAL_CLI_OWNER_ID` 不影响 Web/API 用户。

CLI 只面向 local profile，`LOCAL_CLI_OWNER_ID` 必须改为一个启用账号的真实 UUID，
并为该账号授予 `model.platform`；CLI 固定使用平台模式，不提供 BYOK 和完整删除审批界面。

从 `v1.0.0` 升级时，先停止后端并创建目标账号，再执行以下命令。脚本会在 `data/migration-backups/<UTC时间>/` 中创建完整备份，然后迁移原 `local-user` 的数据库、Checkpoint、知识文件和向量元数据：

```powershell
python -m scripts.migrate_local_user --username admin --confirm
```

## 7. 数据库配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_DATABASE_PATH` | `data/lifepilot.db` | 业务数据和会话索引数据库 |
| `CHECKPOINT_DATABASE_PATH` | `data/checkpoints.db` | LangGraph Checkpoint 数据库 |

相对路径会自动解析到项目根目录。应用首次运行时会创建所需父目录和数据表。

建议同时备份两个数据库。只备份应用数据库会丢失 LangGraph 执行状态；只备份 Checkpoint 数据库则会丢失会话索引和业务数据。

## 8. 日志配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | `DEBUG`、`INFO`、`WARNING`、`ERROR` 或 `CRITICAL` |
| `LOG_FILE_PATH` | `logs/lifepilot.log` | 轮转日志文件路径 |
| `LOG_MAX_BYTES` | `1000000` | 单个日志文件最大字节数 |
| `LOG_BACKUP_COUNT` | `3` | 保留的轮转文件数量，至少为 1 |

日志会包含 request ID、运行环境和错误上下文。不要主动记录完整请求 Header、环境变量或用户密钥。

## 9. LangSmith 可观测性

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `APP_ENVIRONMENT` | 否 | `development` | `development`、`test` 或 `production` |
| `LANGSMITH_TRACING` | 否 | `false` | 是否启用 LangSmith 追踪 |
| `LANGSMITH_API_KEY` | 条件必填 | 空 | 启用追踪时必须提供 |
| `LANGSMITH_PROJECT` | 否 | `lifepilot-development` | LangSmith 项目名称 |
| `LANGSMITH_ENDPOINT` | 否 | `https://apac.api.smith.langchain.com` | LangSmith 服务地址 |
| `LANGSMITH_WORKSPACE_ID` | 否 | 空 | 可选工作区 ID |
| `LANGSMITH_HIDE_INPUTS` | 否 | `false` | 是否隐藏发送到追踪平台的输入 |
| `LANGSMITH_HIDE_OUTPUTS` | 否 | `false` | 是否隐藏发送到追踪平台的输出 |

个人聊天和知识库内容可能包含隐私信息。公开展示项目时建议保持追踪关闭；如需启用，应评估数据发送范围，并根据需要设置 `LANGSMITH_HIDE_INPUTS=true` 和 `LANGSMITH_HIDE_OUTPUTS=true`。

## 10. Checkpoint 序列化

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LANGGRAPH_STRICT_MSGPACK` | `true` | 强制 Checkpoint 使用严格 msgpack 序列化 |

该值由应用在启动时写入运行环境，以减少不可移植对象进入持久化状态的风险。

## 11. 知识库配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `KNOWLEDGE_SOURCE_DIRECTORY` | `knowledge_base` | 原始知识文档目录 |
| `CHROMA_PERSIST_DIRECTORY` | `data/chroma` | Chroma 持久化目录 |
| `EMBEDDING_MODEL_NAME` | `models/bge-small-zh-v1.5` | 本地 Hugging Face 模型路径 |
| `EMBEDDING_DEVICE` | `cpu` | `cpu` 或 `cuda` |
| `KNOWLEDGE_CHUNK_SIZE` | `700` | 文本块长度 |
| `KNOWLEDGE_CHUNK_OVERLAP` | `120` | 相邻文本块重叠长度 |
| `KNOWLEDGE_RETRIEVAL_K` | `4` | 每次检索返回的文档块数量 |
| `KNOWLEDGE_MAX_FILE_BYTES` | `20000000` | 单个上传文件最大字节数 |

`KNOWLEDGE_CHUNK_OVERLAP` 必须小于 `KNOWLEDGE_CHUNK_SIZE`，否则应用会在启动阶段拒绝配置。

知识文件、模型和向量索引默认不会进入 Git。不要把私人资料放进 `evaluations/fixtures/`，因为该目录属于公开的测试数据。

## 12. Streamlit 后端地址

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LIFEPILOT_API_URL` | `http://127.0.0.1:8000` | Streamlit 调用的 FastAPI 地址 |

本地运行时保持默认值即可。如果 API 使用其他端口，应同步修改该配置。

## 13. 推荐本地配置

```env
DEEPSEEK_API_KEY=replace-with-real-key
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_TIMEOUT_SECONDS=60
DEEPSEEK_MAX_RETRIES=2

AUTH_SESSION_TTL_HOURS=168
AUTH_SESSION_TOUCH_INTERVAL_SECONDS=300
AUTH_LOGIN_MAX_FAILURES=5
AUTH_LOGIN_WINDOW_SECONDS=900
REGISTRATION_MODE=closed
AUTH_REGISTRATION_MAX_FAILURES=10
AUTH_REGISTRATION_WINDOW_SECONDS=900
AUTH_INVITATION_MAX_TTL_HOURS=720
API_RATE_LIMIT_ENABLED=true
API_RATE_LIMIT_REQUESTS=60
API_RATE_LIMIT_WINDOW_SECONDS=60

AGENT_RECURSION_LIMIT=25
LOCAL_CLI_OWNER_ID=local-user
DEFAULT_THREAD_ID=main

APP_ENVIRONMENT=development
LANGSMITH_TRACING=false

LIFEPILOT_API_URL=http://127.0.0.1:8000
```

除密钥外，其余未列出的值可以继续使用 `.env.example` 中的默认配置。
