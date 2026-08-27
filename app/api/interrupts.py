"""解析并规范化 LangGraph 人工审批中断。"""

from typing import Any


def get_interrupt_value(
    interrupt_object: Any,
) -> Any:
    """从不同版本的 LangGraph Interrupt 对象中读取业务值。"""

    return getattr(
        interrupt_object,
        "value",
        interrupt_object,
    )


def extract_invoke_interrupt(
    result: Any,
) -> Any | None:
    """从图调用结果中提取本轮产生的中断。"""

    output_interrupts = getattr(
        result,
        "interrupts",
        (),
    )

    if output_interrupts:
        return get_interrupt_value(output_interrupts[0])

    if isinstance(result, dict):
        interrupts = result.get(
            "__interrupt__",
            (),
        )

        if interrupts:
            return get_interrupt_value(interrupts[0])

    return None


def find_pending_interrupt(
    graph: Any,
    config: dict[str, Any],
) -> Any | None:
    """从已保存的图状态中查找尚未处理的中断。"""

    snapshot = graph.get_state(config)

    for task in getattr(
        snapshot,
        "tasks",
        (),
    ):
        task_interrupts = getattr(
            task,
            "interrupts",
            (),
        )

        if task_interrupts:
            return get_interrupt_value(task_interrupts[0])

    return None


def normalize_approval_request(
    value: Any,
) -> dict[str, Any]:
    """将审批中断转换为稳定的 JSON 字典。"""

    if isinstance(value, dict):
        return value

    return {
        "kind": "tool_approval",
        "tool_name": "unknown",
        "message": str(value),
        "arguments": {},
    }
