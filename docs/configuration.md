# 配置说明

## 1. 配置加载规则

LifePilot 使用 Pydantic Settings 读取项目根目录的 `.env` 和进程环境变量。字段名不区分大小写，环境变量优先级高于 `.env`。

创建本地配置：

```powershell
Copy-Item .env.example .env
```

`.env` 包含真实密钥和本地路径，已被 `.gitignore` 排除，不得提交。`.env.example` 只保存安全的默认值和空占位符。

## 2. 最小可运行配置

```env
DEEPSEEK_API_KEY=your-deepseek-api-key
```

知识库还要求本地 Embedding 模型存在于默认路径：

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
| `DEEPSEEK_API_KEY` | 是 | 无 | DeepSeek API 密钥，使用 SecretStr 保存 |
| `DEEPSEEK_MODEL` | 否 | `deepseek-v4-flash` | 聊天模型名称 |
| `DEEPSEEK_TIMEOUT_SECONDS` | 否 | `60` | 单次模型请求超时秒数，必须大于 0 |
| `DEEPSEEK_MAX_RETRIES` | 否 | `2` | 模型客户端最大重试次数，范围 0～10 |

模型重试只覆盖模型客户端请求，不会自动重放完整 Agent 工作流，以避免重复执行写入类工具。

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
| `API_RATE_LIMIT_ENABLED` | 否 | `true` | 是否启用进程内限流 |
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

以下端点保持公开：

- `/api/v1/auth/login`
- `/api/v1/health`
- `/api/v1/ready`
- `/docs`
- `/openapi.json`

登录成功后 API 返回一次原始 Session 令牌，客户端通过 `Authorization: Bearer <token>` 访问其他接口；数据库只保存令牌摘要。Streamlit 仅在当前浏览器 Session 中保存原始令牌，不写入 `.env`、Cookie 或磁盘。

登录失败限流按客户端 IP 和用户名摘要计数，业务限流按 Session 摘要计数。两个限流器都保存在进程内存中，服务重启后计数清空，不支持多 Worker 共享。

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
