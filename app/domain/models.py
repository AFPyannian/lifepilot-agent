"""定义与具体持久化技术无关的业务数据结构。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuditEvent:
    """表示后台可查询的一条脱敏审计事件。"""

    id: str
    request_id: str
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    created_at: datetime


@dataclass(frozen=True)
class Conversation:
    """表示一条会话元数据记录。"""

    owner_id: str
    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class NoteItem:
    """表示一条用户笔记。"""

    id: int
    owner_id: str
    title: str
    content: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class TodoItem:
    """表示一条用户待办事项。"""

    id: int
    owner_id: str
    task: str
    is_completed: bool
    created_at: str


@dataclass(frozen=True)
class UserProfile:
    """表示用户的结构化资料。"""

    owner_id: str
    display_name: str | None
    occupation: str | None
    current_goal: str | None
    response_style: str | None
    updated_at: str


@dataclass(frozen=True)
class UserMemory:
    """表示一条用户长期记忆。"""

    id: int
    owner_id: str
    category: str
    content: str
    created_at: str
    updated_at: str
