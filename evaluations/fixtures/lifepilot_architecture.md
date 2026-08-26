# LifePilot 架构

LifePilot 使用 LangGraph 组织 Agent 工作流。

DeepSeek 负责语言理解和工具调用。

FastAPI 提供 HTTP 及 SSE 接口，Streamlit 负责聊天界面。

Chroma 用于存储个人知识库的文本向量。