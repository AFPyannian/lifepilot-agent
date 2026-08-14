"""
定义 LangGraph 状态、节点和边。
"""
from typing import Annotated

from langchain_core.messages import (
    AnyMessage,
    SystemMessage,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.model import create_model

# 系统提示词是优先级最高的。
SYSTEM_PROMPT = """
你是 LifePilot，一个简洁、可靠的中文个人助理。

请遵守以下要求：
1. 优先使用清晰、简洁的中文回答。
2. 不确定的信息要明确说明不确定。
3. 不要声称自己已经执行了实际未执行的操作。""".strip()         # .strip() 会去掉用户输入内容开头和结尾的空格、换行符等空白字符。



class AssistantState(TypedDict):
    """定义状态：工作流执行期间共享的数据（图中所有节点共享的数据）"""

    # 状态合并规则（决定节点返回新消息时，替换旧消息还是追加到旧消息后边）
    messages: Annotated[list[AnyMessage], add_messages]


def build_graph():
    """构建整个 LifePilot 工作流，并最终返回一个可以执行的 graph。"""

    # 实例化模型
    model = create_model()


    def assistant_node(state: AssistantState,) -> dict:     # 函数写法含义: 接收参数state(AssistantState类型), 返回一个字典.
        """创建节点: 接收当前状态,执行某项任务,返回需要更新的部分状态.(调用语言模型，并返回模型的回复)"""

        # 组装将要传递给模型的提示词消息。
        messages_for_model = [
            SystemMessage(content=SYSTEM_PROMPT),
            *state["messages"],
        ]

        # 将提示词消息传递给模型，并调用模型得到回复。
        response = model.invoke(messages_for_model)

        # 函数定义返回字典，因此在这里包装为字典类型。
        return {"messages": [response]}

    # 创建工作流图(是一个空图,等待添加节点)
    builder = StateGraph(AssistantState)

    # 添加节点(添加到节点到上边创建的空图中)
    builder.add_node(
        "assistant",        # 将要添加的节点命名为"assistant"
        assistant_node,     # 将要添加的节点函数
    )

    # 添加边(工作流开始 → assistant)
    builder.add_edge(
        START,
        "assistant",
    )

    # 添加边(assistant → 工作流结束)
    builder.add_edge(
        "assistant",
        END,
    )

    checkpointer = InMemorySaver()

    # 编译图: 根据定义好的节点和边，生成一个真正可以执行的工作流对象。
    return builder.compile(
        checkpointer=checkpointer,
    )