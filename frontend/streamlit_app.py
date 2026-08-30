"""构建 LifePilot Streamlit 交互界面。"""

import os
import sys
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Streamlit 以 frontend 目录执行脚本，需要显式加入项目根目录。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.clients import (  # noqa: E402
    ApprovalRequired,
    LifePilotApiClient,
    LifePilotApiError,
)

load_dotenv(PROJECT_ROOT / ".env")

API_BASE_URL = (os.getenv("LIFEPILOT_API_URL") or "http://127.0.0.1:8000").rstrip("/")


st.set_page_config(
    page_title="LifePilot",
    page_icon="🧭",
    layout="centered",
)


def create_thread_id() -> str:
    """生成符合后端校验规则的随机会话标识。"""

    return f"web-{uuid4().hex}"


def initialize_session_state() -> None:
    """初始化当前浏览器会话所需的状态。"""

    if "thread_id" not in st.session_state:
        st.session_state.thread_id = create_thread_id()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "pending_approval" not in st.session_state:
        st.session_state.pending_approval = None

    if "access_token" not in st.session_state:
        st.session_state.access_token = None

    if "current_user" not in st.session_state:
        st.session_state.current_user = None


def clear_authenticated_state() -> None:
    """清除当前 Streamlit 会话中的登录和聊天状态。"""
    st.session_state.access_token = None
    st.session_state.current_user = None
    st.session_state.thread_id = create_thread_id()
    st.session_state.messages = []
    st.session_state.pending_approval = None


@st.cache_data(
    ttl=5,
    show_spinner=False,
)
def check_backend_health(
    base_url: str,
) -> bool:
    """缓存并返回后端健康状态。"""

    client = LifePilotApiClient(base_url=base_url)

    return client.is_healthy()


@st.cache_data(
    ttl=30,
    show_spinner=False,
)
def get_registration_status(base_url: str) -> dict:
    """短时间缓存后端注册状态。"""
    client = LifePilotApiClient(base_url=base_url)
    try:
        return client.get_registration_status()
    except LifePilotApiError:
        return {"mode": "closed", "enabled": False}


initialize_session_state()

backend_available = check_backend_health(API_BASE_URL)

if not st.session_state.access_token:
    st.title("🧭 LifePilot")
    st.caption("请登录或使用管理员提供的邀请码注册")

    anonymous_client = LifePilotApiClient(base_url=API_BASE_URL)
    registration_status = get_registration_status(API_BASE_URL)
    registration_enabled = bool(registration_status.get("enabled"))

    if registration_enabled:
        login_tab, register_tab = st.tabs(["登录", "注册"])
    else:
        login_tab = st.container()
        register_tab = None

    with login_tab:
        with st.form("login-form", clear_on_submit=False):
            username = st.text_input(
                "用户名",
                max_chars=64,
                autocomplete="username",
            )
            password = st.text_input(
                "密码",
                type="password",
                max_chars=1024,
                autocomplete="current-password",
            )
            login_clicked = st.form_submit_button(
                "登录",
                type="primary",
                use_container_width=True,
                disabled=not backend_available,
            )

        if login_clicked:
            try:
                login_result = anonymous_client.login(username, password)
                st.session_state.access_token = login_result["access_token"]
                st.session_state.current_user = login_result["user"]
                st.rerun()
            except (KeyError, LifePilotApiError) as error:
                st.error(str(error))

    if register_tab is not None:
        with register_tab:
            with st.form("registration-form", clear_on_submit=True):
                register_username = st.text_input(
                    "注册用户名",
                    max_chars=64,
                    autocomplete="username",
                )
                register_password = st.text_input(
                    "设置密码",
                    type="password",
                    max_chars=1024,
                    autocomplete="new-password",
                    help="密码至少需要12个字符。",
                )
                confirm_password = st.text_input(
                    "确认密码",
                    type="password",
                    max_chars=1024,
                    autocomplete="new-password",
                )
                invite_code = st.text_input(
                    "邀请码",
                    type="password",
                    max_chars=256,
                    autocomplete="off",
                )
                register_clicked = st.form_submit_button(
                    "创建账号",
                    type="primary",
                    use_container_width=True,
                    disabled=not backend_available,
                )

            if register_clicked:
                if register_password != confirm_password:
                    st.error("两次输入的密码不一致。")
                elif len(register_password) < 12:
                    st.error("密码至少需要12个字符。")
                else:
                    try:
                        result = anonymous_client.register(
                            username=register_username,
                            password=register_password,
                            invite_code=invite_code,
                        )
                        st.session_state.access_token = result["access_token"]
                        st.session_state.current_user = result["user"]
                        st.success("账号创建成功。")
                        st.rerun()
                    except (KeyError, LifePilotApiError) as error:
                        st.error(str(error))

    if not backend_available:
        st.error("后端服务未连接，请先启动 FastAPI。")

    st.stop()


client = LifePilotApiClient(
    base_url=API_BASE_URL,
    access_token=st.session_state.access_token,
)

if st.session_state.current_user is None:
    try:
        st.session_state.current_user = client.get_current_user()
    except LifePilotApiError:
        clear_authenticated_state()
        st.rerun()


with st.sidebar:
    st.header("🧭 LifePilot")

    current_user = st.session_state.current_user
    st.caption("当前账号")
    st.write(f"👤 {current_user['username']}")

    if st.button(
        "退出登录",
        use_container_width=True,
    ):
        with suppress(LifePilotApiError):
            client.logout()
        clear_authenticated_state()
        st.rerun()

    if current_user.get("role") == "admin":
        with st.expander("注册邀请"):
            expires_in_hours = st.number_input(
                "有效期（小时）",
                min_value=1,
                max_value=720,
                value=72,
                step=1,
            )

            if st.button(
                "生成一次性邀请码",
                use_container_width=True,
            ):
                try:
                    invitation = client.create_invitation(int(expires_in_hours))
                    st.success("请立即复制；刷新后无法再次查看原文。")
                    st.code(invitation["invite_code"], language=None)
                except (KeyError, LifePilotApiError) as error:
                    st.error(str(error))

            try:
                invitations = client.list_invitations()
            except LifePilotApiError as error:
                invitations = []
                st.warning(str(error))

            for invitation in invitations:
                invitation_id = invitation["id"]
                if invitation.get("used_at"):
                    invitation_state = f"已使用：{invitation.get('used_by_username')}"
                elif invitation.get("revoked_at"):
                    invitation_state = "已撤销"
                else:
                    invitation_state = "未使用"

                st.caption(
                    f"{invitation_id[:8]} · {invitation_state} · "
                    f"过期：{invitation['expires_at']}"
                )

                if invitation_state == "未使用" and st.button(
                    "撤销",
                    key=f"revoke-invite-{invitation_id}",
                ):
                    try:
                        client.revoke_invitation(invitation_id)
                        st.success("邀请码已经撤销。")
                        st.rerun()
                    except LifePilotApiError as error:
                        st.error(str(error))

    st.divider()

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
        st.session_state.thread_id = create_thread_id()

        st.session_state.messages = []

        st.session_state.pending_approval = None

        check_backend_health.clear()
        st.rerun()

    if st.button(
        "重新检查后端",
        use_container_width=True,
    ):
        check_backend_health.clear()
        st.rerun()

    st.divider()
    st.subheader("历史会话")

    conversations: list[dict] = []

    if backend_available:
        try:
            conversations = client.list_conversations()

        except LifePilotApiError as error:
            st.warning(str(error))

    if conversations:
        conversation_ids = [conversation["thread_id"] for conversation in conversations]

        title_by_id = {
            conversation["thread_id"]: (conversation["title"])
            for conversation in conversations
        }

        current_thread_id = st.session_state.thread_id

        default_index = 0

        if current_thread_id in conversation_ids:
            default_index = conversation_ids.index(current_thread_id)

        selected_thread_id = st.selectbox(
            "选择会话",
            options=conversation_ids,
            index=default_index,
            format_func=lambda thread_id: title_by_id.get(
                thread_id,
                thread_id,
            ),
        )

        if st.button(
            "加载会话",
            use_container_width=True,
        ):
            try:
                detail = client.get_conversation(selected_thread_id)

                st.session_state.thread_id = detail["thread_id"]

                st.session_state.messages = detail.get(
                    "messages",
                    [],
                )

                st.session_state.pending_approval = detail.get("pending_approval")

                st.rerun()

            except LifePilotApiError as error:
                st.error(str(error))

        new_title = st.text_input(
            "修改会话标题",
            value=title_by_id.get(
                selected_thread_id,
                "",
            ),
            max_chars=80,
            key=(f"conversation-title-{selected_thread_id}"),
        )

        if st.button(
            "保存新标题",
            use_container_width=True,
            disabled=not new_title.strip(),
        ):
            try:
                client.rename_conversation(
                    thread_id=(selected_thread_id),
                    title=new_title,
                )

                st.success("会话标题已更新。")

                st.rerun()

            except LifePilotApiError as error:
                st.error(str(error))

        confirm_conversation_delete = st.checkbox(
            "我确认删除选中的整个会话",
            key=(f"confirm-conversation-delete-{selected_thread_id}"),
        )

        if st.button(
            "删除会话",
            use_container_width=True,
            disabled=(not confirm_conversation_delete),
        ):
            try:
                deleted = client.delete_conversation(selected_thread_id)

                if deleted:
                    if st.session_state.thread_id == selected_thread_id:
                        st.session_state.thread_id = create_thread_id()

                        st.session_state.messages = []

                        st.session_state.pending_approval = None

                    st.success("会话已经删除。")

                    st.rerun()

                else:
                    st.info("会话已经不存在。")

            except LifePilotApiError as error:
                st.error(str(error))

    else:
        st.caption("还没有历史会话")

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
        disabled=(not backend_available or uploaded_file is None),
    ):
        try:
            with st.spinner("正在解析和向量化文档……"):
                result = client.upload_document(
                    filename=(uploaded_file.name),
                    content=(uploaded_file.getvalue()),
                    content_type=(uploaded_file.type or ("application/octet-stream")),
                )

            if result["already_indexed"]:
                st.info(f"{result['filename']} 已经导入，不需要重复向量化。")
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
            documents = client.list_documents()

        except LifePilotApiError as error:
            st.warning(str(error))

    if documents:
        st.caption(f"当前共有 {len(documents)} 个知识文档")

        for document in documents:
            st.write(f"📄 {document['filename']} ({document['chunk_count']} 块)")

        selected_filename = st.selectbox(
            "选择需要删除的文档",
            options=[document["filename"] for document in documents],
        )

        confirm_delete = st.checkbox("我确认删除该文档")

        if st.button(
            "删除选中文档",
            use_container_width=True,
            disabled=not confirm_delete,
        ):
            try:
                deleted = client.delete_document(selected_filename)

                if deleted:
                    st.success(f"已删除：{selected_filename}")
                    st.rerun()
                else:
                    st.info("该文档已经不存在。")

            except LifePilotApiError as error:
                st.error(str(error))

    else:
        st.caption("知识库中还没有文档")

    st.caption("LifePilot 使用 LangGraph、DeepSeek、FastAPI 和 Streamlit 构建。")


st.title("🧭 LifePilot")
st.caption("你的个人智能助理")


if not st.session_state.messages:
    st.info(
        "你可以让我管理待办、记录笔记、保存长期记忆、查询个人知识库，或者进行普通对话。"
    )


for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


pending_approval = st.session_state.pending_approval

if pending_approval is not None:
    st.warning(
        pending_approval.get(
            "message",
            ("LifePilot 请求执行一项敏感操作。"),
        )
    )

    tool_name = pending_approval.get(
        "tool_name",
        "未知工具",
    )

    st.write(f"工具名称：`{tool_name}`")

    with st.expander("查看操作参数"):
        st.json(
            pending_approval.get(
                "arguments",
                {},
            )
        )

    approve_column, reject_column = st.columns(2)

    with approve_column:
        approve_clicked = st.button(
            "批准执行",
            type="primary",
            use_container_width=True,
        )

    with reject_column:
        reject_clicked = st.button(
            "拒绝执行",
            use_container_width=True,
        )

    if approve_clicked or reject_clicked:
        approved = approve_clicked

        try:
            with st.spinner("正在恢复 Agent 执行……"):
                reply = client.resume_chat(
                    thread_id=(st.session_state.thread_id),
                    approved=approved,
                )

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": reply,
                }
            )

            st.session_state.pending_approval = None

            st.rerun()

        except ApprovalRequired as error:
            st.session_state.pending_approval = error.request

            st.rerun()

        except LifePilotApiError as error:
            st.error(str(error))

    st.stop()


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

    st.session_state.messages.append(user_message)

    with st.chat_message("user"):
        st.markdown(prompt)

    received_chunks: list[str] = []

    def collect_response():
        """收集流式回答并同步更新页面消息。"""
        for token in client.stream_chat(
            message=prompt,
            thread_id=(st.session_state.thread_id),
        ):
            received_chunks.append(token)
            yield token

    with st.chat_message("assistant"):
        try:
            complete_response = st.write_stream(
                collect_response(),
                cursor="▌",
            )

            if not isinstance(
                complete_response,
                str,
            ):
                complete_response = "".join(received_chunks)

            if not complete_response.strip():
                raise LifePilotApiError("后端完成了请求，但没有返回可显示的文本。")

            assistant_message = {
                "role": "assistant",
                "content": complete_response,
            }

            st.session_state.messages.append(assistant_message)

        except ApprovalRequired as error:
            partial_response = "".join(received_chunks)

            if partial_response:
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": partial_response,
                    }
                )

            st.session_state.pending_approval = error.request

            st.rerun()

        except LifePilotApiError as error:
            partial_response = "".join(received_chunks)

            if partial_response:
                incomplete_message = (
                    partial_response + "\n\n" + "> 回答因连接或后端异常而中断。"
                )

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": (incomplete_message),
                    }
                )

            st.error(str(error))
