import os
from pathlib import Path
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

from app.clients import (
    LifePilotApiClient,
    LifePilotApiError,
)


PROJECT_ROOT = (
    Path(__file__).resolve().parent.parent
)

load_dotenv(
    PROJECT_ROOT / ".env"
)

API_BASE_URL = (
    os.getenv("LIFEPILOT_API_URL")
    or "http://127.0.0.1:8000"
).rstrip("/")


st.set_page_config(
    page_title="LifePilot",
    page_icon="🧭",
    layout="centered",
)


def create_thread_id() -> str:
    """生成符合 API 校验规则的会话 ID。"""

    return f"web-{uuid4().hex}"


def initialize_session_state() -> None:
    """初始化当前浏览器会话状态。"""

    if "thread_id" not in st.session_state:
        st.session_state.thread_id = (
            create_thread_id()
        )

    if "messages" not in st.session_state:
        st.session_state.messages = []


@st.cache_data(
    ttl=5,
    show_spinner=False,
)
def check_backend_health(
    base_url: str,
) -> bool:
    """短暂缓存健康检查结果。"""

    client = LifePilotApiClient(
        base_url=base_url
    )

    return client.is_healthy()


initialize_session_state()

client = LifePilotApiClient(
    base_url=API_BASE_URL
)

backend_available = check_backend_health(
    API_BASE_URL
)


with st.sidebar:
    st.header("🧭 LifePilot")

    if backend_available:
        st.success("后端服务正常")
    else:
        st.error("后端服务未连接")

    st.caption("FastAPI 地址")

    st.code(
        API_BASE_URL,
        language=None,
    )

    st.caption("当前会话 ID")

    st.code(
        st.session_state.thread_id,
        language=None,
    )

    if st.button(
        "开始新对话",
        use_container_width=True,
    ):
        st.session_state.thread_id = (
            create_thread_id()
        )

        st.session_state.messages = []

        # 清除健康检查缓存，
        # 同时重新执行页面。
        check_backend_health.clear()
        st.rerun()

    if st.button(
        "重新检查后端",
        use_container_width=True,
    ):
        check_backend_health.clear()
        st.rerun()

    st.divider()
    st.subheader("个人知识库")

    uploaded_file = st.file_uploader(
        "上传知识文档",
        type=["txt", "md", "pdf"],
        accept_multiple_files=False,
        max_upload_size=20,
        disabled=not backend_available,
    )

    if st.button(
            "导入知识库",
            use_container_width=True,
            disabled=(
                    not backend_available
                    or uploaded_file is None
            ),
    ):
        try:
            with st.spinner(
                    "正在解析和向量化文档……"
            ):
                result = (
                    client.upload_document(
                        filename=(
                            uploaded_file.name
                        ),
                        content=(
                            uploaded_file
                            .getvalue()
                        ),
                        content_type=(
                                uploaded_file.type
                                or (
                                    "application/"
                                    "octet-stream"
                                )
                        ),
                    )
                )

            if result["already_indexed"]:
                st.info(
                    f"{result['filename']} "
                    "已经导入，不需要重复"
                    "向量化。"
                )
            else:
                st.success(
                    f"已导入 "
                    f"{result['filename']}，"
                    f"生成 "
                    f"{result['chunk_count']} "
                    "个文本块。"
                )

        except LifePilotApiError as error:
            st.error(str(error))

    documents: list[dict] = []

    if backend_available:
        try:
            documents = (
                client.list_documents()
            )

        except LifePilotApiError as error:
            st.warning(str(error))

    if documents:
        st.caption(
            f"当前共有 {len(documents)} "
            "个知识文档"
        )

        for document in documents:
            st.write(
                f"📄 {document['filename']} "
                f"({document['chunk_count']} 块)"
            )

        selected_filename = st.selectbox(
            "选择需要删除的文档",
            options=[
                document["filename"]
                for document in documents
            ],
        )

        confirm_delete = st.checkbox(
            "我确认删除该文档"
        )

        if st.button(
                "删除选中文档",
                use_container_width=True,
                disabled=not confirm_delete,
        ):
            try:
                deleted = (
                    client.delete_document(
                        selected_filename
                    )
                )

                if deleted:
                    st.success(
                        "已删除："
                        f"{selected_filename}"
                    )
                    st.rerun()
                else:
                    st.info(
                        "该文档已经不存在。"
                    )

            except LifePilotApiError as error:
                st.error(str(error))

    else:
        st.caption(
            "知识库中还没有文档"
        )

    st.caption(
        "LifePilot 使用 LangGraph、"
        "DeepSeek、FastAPI 和 Streamlit 构建。"
    )


st.title("🧭 LifePilot")
st.caption("你的个人智能助理")


if not st.session_state.messages:
    st.info(
        "你可以让我管理待办、记录笔记、"
        "保存长期记忆、查询个人知识库，"
        "或者进行普通对话。"
    )


for message in st.session_state.messages:
    with st.chat_message(
        message["role"]
    ):
        st.markdown(
            message["content"]
        )


prompt = st.chat_input(
    placeholder="给 LifePilot 发送消息……",
    max_chars=10_000,
    disabled=not backend_available,
)


if prompt:
    user_message = {
        "role": "user",
        "content": prompt,
    }

    st.session_state.messages.append(
        user_message
    )

    with st.chat_message("user"):
        st.markdown(prompt)

    received_chunks: list[str] = []

    def collect_response():
        for token in client.stream_chat(
            message=prompt,
            thread_id=(
                st.session_state.thread_id
            ),
        ):
            received_chunks.append(token)
            yield token

    with st.chat_message("assistant"):
        try:
            complete_response = (
                st.write_stream(
                    collect_response(),
                    cursor="▌",
                )
            )

            # 当前生成器只返回字符串，
            # 正常情况下 write_stream 返回完整字符串。
            if not isinstance(
                complete_response,
                str,
            ):
                complete_response = "".join(
                    received_chunks
                )

            if not complete_response.strip():
                raise LifePilotApiError(
                    "后端完成了请求，"
                    "但没有返回可显示的文本。"
                )

            assistant_message = {
                "role": "assistant",
                "content": complete_response,
            }

            st.session_state.messages.append(
                assistant_message
            )

        except LifePilotApiError as error:
            partial_response = "".join(
                received_chunks
            )

            if partial_response:
                incomplete_message = (
                    partial_response
                    + "\n\n"
                    + "> 回答因连接或后端异常而中断。"
                )

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": (
                            incomplete_message
                        ),
                    }
                )

            st.error(str(error))