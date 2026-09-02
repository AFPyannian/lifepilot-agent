# 测试与代码质量

## 1. 质量目标

LifePilot 的测试策略重点验证以下风险：

- Agent 是否选择并正确执行工具。
- SQLite 数据是否按 owner 和 thread 隔离。
- Checkpoint 是否能恢复中断的工作流。
- 删除操作是否必须经过人工审批。
- RAG 是否能导入、检索和删除正确文档。
- API、流式 SSE 和客户端协议是否保持一致。
- Session 认证、账号状态和跨用户数据边界是否可靠。
- 邀请码是否只能消费一次，普通用户是否被管理员接口拒绝。
- 配置错误、外部模型错误和安全限制是否被正确处理。

自动化测试默认离线运行，不调用真实 DeepSeek API，也不读取个人知识文档。

## 2. 开发环境

测试要求 Python 3.11：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

`requirements-dev.txt` 会同时安装生产依赖和开发工具。

## 3. 测试分层

### 3.1 Repository 测试

Repository 测试使用临时 SQLite 数据库验证完整行为，并通过共享 Protocol
对 SQLite/PostgreSQL 适配器执行结构契约检查。SQLite 行为测试覆盖：

- CRUD。
- owner 数据隔离。
- 排序和搜索。
- 不存在资源的返回行为。
- 会话标题、更新时间和消息记录。

显式启用的生产集成测试另外验证 PostgreSQL/pgvector 与 Checkpoint 表、跨连接
配额原子性、Redis 共享滑动窗口和 MinIO 私有对象往返。

对应文件包括：

```text
tests/test_todo_repository.py
tests/test_note_repository.py
tests/test_user_memory_repository.py
tests/test_conversation_repository.py
tests/test_auth_repository.py
tests/test_repository_factory.py
```

### 3.2 Tool 测试

工具测试验证输入、Repository 调用和面向模型的文本输出，不依赖真实模型：

```text
tests/test_tools.py
tests/test_note_tools.py
tests/test_memory_tools.py
tests/test_knowledge_tools.py
```

### 3.3 Graph 与 Checkpoint 测试

Graph 测试注入 Fake Model 和临时 Checkpointer，验证：

- 普通回答路径。
- 模型工具调用路径。
- 工具错误处理。
- 用户记忆注入。
- 不完整工具调用历史清理。
- Checkpoint 持久化和恢复。

对应文件：

```text
tests/test_graph.py
tests/test_checkpointing.py
```

### 3.4 API 与客户端测试

FastAPI TestClient 和 HTTPX MockTransport 用于验证：

- 健康和就绪端点。
- 普通聊天和流式聊天。
- 审批中断与恢复。
- 会话和知识库管理。
- 登录、Session 撤销、密码修改和登录限流。
- 注册关闭、邀请码注册、角色注入拒绝和注册限流。
- 邀请码过期、撤销、并发消费及秘密不落库。
- 同名 thread ID、会话详情和知识文件的跨用户隔离。
- 请求限流和安全响应头。
- Request ID。
- Streamlit API Client 请求格式。
- AES-GCM 凭据加密、防篡改和跨用户密文调换。
- 用户 Key 创建、轮换、撤销、删除及明文不落库。
- BYOK/PLATFORM 模型路由和单用户认证失败隔离。
- 既有用户授权迁移、新用户默认无平台授权、授权过期与撤销。
- API 拒绝发生在会话写入前，模型网关再次执行能力校验。
- 用量事件幂等状态流转、跨用户隔离、Token 提取与汇总 API。

这些测试通过 `create_app()` 注入 Fake Graph、临时 Repository 和知识库服务，不启动真实 Uvicorn。

## 4. 运行测试

运行全部测试：

```powershell
python -m pytest
```

运行单个测试文件：

```powershell
python -m pytest tests/test_api_security.py -q
```

运行单个测试：

```powershell
python -m pytest tests/test_auth_api.py::test_login_and_logout_lifecycle -q
```

运行覆盖率：

```powershell
python -m pytest `
    --cov=app `
    --cov-branch `
    --cov-report=term-missing `
    --cov-report=html
```

HTML 报告生成在：

```text
htmlcov/index.html
```

`pyproject.toml` 当前要求总体分支覆盖率不低于 60%。覆盖率门槛是最低保护线，不代表每个模块都达到同一比例；认证、数据删除、审批和持久化等高风险路径应优先获得更完整覆盖。

## 5. pytest markers

项目定义了两个 marker：

| Marker | 含义 |
| --- | --- |
| `integration` | 需要多个真实组件协作，但不一定访问公网 |
| `live` | 访问真实外部 API，可能产生费用 |

排除 live 测试：

```powershell
python -m pytest -m "not live"
```

CI 不得运行 live 测试。

## 6. Ruff 与格式检查

检查代码：

```powershell
python -m ruff check .
```

自动修复可安全修复的问题：

```powershell
python -m ruff check . --fix
```

格式化：

```powershell
python -m ruff format .
```

只验证格式：

```powershell
python -m ruff format --check .
```

## 7. mypy 类型检查

```powershell
python -m mypy app
```

当前类型检查范围是生产后端代码 `app/`。配置启用了已注解函数检查、禁止隐式 Optional、冗余 cast 和无效 ignore 警告。

## 8. 统一质量脚本

Windows PowerShell 下运行：

```powershell
.\scripts\quality.ps1
```

脚本会先确认 Python 版本为 3.11，然后按顺序运行：

1. `ruff check .`
2. `ruff format --check .`
3. `mypy app`
4. `pytest` 与 branch coverage

任意一步失败都会停止脚本并返回非零退出码。

## 9. pre-commit 与 pre-push

安装 hooks：

```powershell
pre-commit install --install-hooks
pre-commit install --hook-type pre-push
```

提交前 hook 包括：

- Ruff lint 自动修复。
- Ruff format。
- YAML、JSON 和 TOML 校验。
- 行尾空白及文件结尾修复。
- 合并冲突、文件名大小写冲突和大文件检查。
- 私钥检测。
- mypy。

推送前 hook 会运行 pytest 与覆盖率检查。

手工执行全部提交前 hooks：

```powershell
pre-commit run --all-files
```

手工执行推送前 hooks：

```powershell
pre-commit run --all-files --hook-stage pre-push
```

## 10. GitHub Actions

`.github/workflows/quality.yml` 在以下情况运行：

- push 到 `main`。
- 向 `main` 创建或更新 Pull Request。
- 手工触发 workflow。

CI 使用 Python 3.11，安装 `requirements-dev.txt`，并执行与本地质量脚本等价的 Ruff、mypy 和 pytest 检查。

CI 只注入虚假的 `DEEPSEEK_API_KEY` 供 Settings 初始化，不保存真实 API Key，也不调用外部模型。

## 11. Agent 评估

Agent 评估根据 `evaluations/agent_cases.json` 检查：

- 是否调用必需工具。
- 是否调用了不允许的工具。
- 最终回答是否包含必要关键词。
- 执行耗时是否超过用例阈值。

运行全部 Agent 用例：

```powershell
python -m evaluations.run_agent_eval
```

运行单个用例：

```powershell
python -m evaluations.run_agent_eval --case add_todo
```

修改最低通过率：

```powershell
python -m evaluations.run_agent_eval --minimum-pass-rate 0.8
```

该评估会调用真实 DeepSeek 模型，可能产生费用和非确定性结果，因此不属于 GitHub Actions 的必跑任务。

`tests/test_evaluations.py` 使用确定性模型验证评估图装配、可信用户上下文、工具循环
和报告判定，不访问 DeepSeek；真实模型效果仍由上述命令单独评估。

## 12. RAG 评估

RAG 评估将 `evaluations/fixtures/` 中的公开样例复制到临时的用户隔离目录，导入临时 Chroma 数据库，并根据 `evaluations/rag_cases.json` 计算 Hit@1：

```powershell
python -m evaluations.run_rag_eval
```

当前门槛为 75%。运行前必须准备本地 Embedding 模型，但不会调用 DeepSeek。

## 13. 提交前完整验收

```powershell
.\scripts\quality.ps1
pre-commit run --all-files
pre-commit run --all-files --hook-stage pre-push
git diff --check
git status --short
```

只有在这些检查全部通过、工作区中不存在 `.env`、数据库、日志、模型或私人知识文档时，才应推送到公开仓库。
