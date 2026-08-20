from typing import Annotated, Protocol

from langchain_core.messages import (
    AnyMessage,
    SystemMessage,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import (
    ToolNode,
    tools_condition,
)
from typing_extensions import TypedDict

from app.config import Settings, get_settings
from app.exceptions import (
    LifePilotError,
    ModelServiceError,
)
from app.model import create_model
from app.repositories.note_repository import (
    NoteRepository,
)
from app.repositories.todo_repository import (
    TodoRepository,
)
from app.tools import (
    create_note_tools,
    create_todo_tools,
)


# 系统提示词。优先级最高
SYSTEM_PROMPT = """
你是 LifePilot，一个简洁、可靠的中文个人助理。

请遵守以下要求：
1. 优先使用清晰、简洁的中文回答。
2. 不确定的信息要明确说明不确定。
3. 不要声称自己已经执行了实际未执行的操作。
4. 用户要求添加、查看、完成或删除待办时，必须调用待办工具。
5. 用户要求保存、查看、搜索、修改或删除笔记时，必须调用笔记工具。
6. 如果“用户的描述类似待办事项，但没有明确说明保存为待办”。此时，必须询问用户是否要保存为待办。
7. 如果“用户的描述类似事情陈述，但没有明确说明保存为笔记”。此时，必须询问用户是否要保存为笔记。
8. 必须根据工具返回的真实结果回答，不能编造执行结果。
9. 完成或删除待办需要使用待办ID。
10.查看、修改或删除特定笔记需要使用笔记ID。
11. 用户没有提供必要ID时，应先查看列表、搜索或询问用户。
12. 删除是永久操作，只有用户明确要求删除时才能执行。
""".strip()



class ChatModel(Protocol):
    """
    定义模型接口：任何对象只要拥有符合要求的方法，就可以作为模型传入。(依赖注入)
        "..."是 Ellipsis对象，只定义方法应该长什么样，不编写具体实现。
    """

    # 定义模型必须支持 bind_tools() 方法
    def bind_tools(self, tools):
        ...

    # 定义模型必须支持 invoke() 方法————传入一组消息列表，并返回一个消息对象。
    def invoke(self, messages: list[AnyMessage]) -> AnyMessage:
        ...


class AssistantState(TypedDict):
    """定义状态：工作流执行期间共享的数据（图中所有节点共享的数据）"""

    # 消息字段。Annotated[原始消息, 附加信息]
    messages: Annotated[list[AnyMessage], add_messages]     # 状态合并规则: 节点返回新消息时，直接追加到旧消息后边。


def build_graph(
    settings: Settings | None = None,
    model: ChatModel | None = None,
    checkpointer=None,
    todo_repository: TodoRepository | None = None,
    note_repository: NoteRepository | None = None,
    owner_id: str = "local-user",
):
    """
    构建整个 LifePilot 工作流，并最终返回一个可以执行的 graph。
        第一个参数：model 可以是 ChatModel，也可以是 None，默认为None。
        第二个参数：
    """

    active_settings = settings

    def require_settings() -> Settings:
        nonlocal active_settings

        if active_settings is None:
            active_settings = get_settings()

        return active_settings

    # 确定实际使用模型
    active_model = (
        model
        if model is not None
        else create_model(require_settings())
    )

    # 确定实际使用状态保存器
    active_checkpointer = (
        checkpointer
        if checkpointer is not None
        else InMemorySaver()
    )

    active_todo_repository = (
        todo_repository
        if todo_repository is not None
        else TodoRepository(
            require_settings().app_database_path
        )
    )

    active_note_repository = (
        note_repository
        if note_repository is not None
        else NoteRepository(
            require_settings().app_database_path
        )
    )

    active_owner_id = (
        owner_id
        if owner_id is not None
        else require_settings().owner_id
    )

    todo_tools = create_todo_tools(
        repository=active_todo_repository,
        owner_id=active_owner_id,
    )

    note_tools = create_note_tools(
        repository=active_note_repository,
        owner_id=active_owner_id,
    )

    all_tools = [
        *todo_tools,
        *note_tools,
    ]

    # 为模型绑定工具，让模型知道有哪些工具
    model_with_tools = active_model.bind_tools(
        all_tools
    )

    def assistant_node(state: AssistantState) -> dict:
        """创建节点: 接收当前状态,执行某项任务,返回需要更新的部分状态.(调用语言模型，并返回模型的回复)"""

        # 组装模型消息(组装后的消息会被传递给模型)
        messages_for_model = [
            SystemMessage(content=SYSTEM_PROMPT),       # 系统消息
            *state["messages"],                         # 当前状态中的所有历史消息
        ]

        # 调用模型(将提示词消息传递给模型，并得到模型回复)
        try:
            response = model_with_tools.invoke(
                messages_for_model
            )
        except LifePilotError:
            raise
        except Exception as error:
            raise ModelServiceError(
                "DeepSeek invocation failed."
            ) from error

        # 返回部分状态(加入到状态中的模型新返回消息)
        return {"messages": [response]}

    # 创建工作流图(是一个空图,等待添加节点)
    builder = StateGraph(AssistantState)

    # 注册节点(添加到节点到上边创建的空图中)
    builder.add_node(
        "assistant",        # 将要添加的节点命名为"assistant"
        assistant_node,     # 将要添加的节点函数
    )

    # 注册节点()
    builder.add_node(
        "tools",
        ToolNode(
            all_tools,
            handle_tool_errors=("工具暂时无法执行，请稍后重试。"),
        ),
    )

    # 添加边(工作流开始 → assistant)
    builder.add_edge(
        START,
        "assistant",
    )

    # 条件边(assistant → 如果需要工具就执行,不需要就结束)
    builder.add_conditional_edges(
        "assistant",
        tools_condition,
    )

    # 添加边(assistant → tools)(工具执行后必须再交给模型)
    builder.add_edge(
        "tools",
        "assistant",
    )

    # 编译工作流: 根据定义好的节点和边，生成一个真正可以执行的工作流对象。
    return builder.compile(
        checkpointer=active_checkpointer,
    )