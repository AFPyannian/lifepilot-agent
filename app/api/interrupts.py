from typing import Any


def get_interrupt_value(
    interrupt_object: Any,
) -> Any:
    """从 LangGraph Interrupt 中读取业务值。"""

    return getattr(
        interrupt_object,
        "value",
        interrupt_object,
    )


def extract_invoke_interrupt(
    result: Any,
) -> Any | None:
    """从 invoke() 的执行结果中提取中断。"""

    # 兼容 LangGraph v2 GraphOutput。
    output_interrupts = getattr(
        result,
        "interrupts",
        (),
    )

    if output_interrupts:
        return get_interrupt_value(
            output_interrupts[0]
        )

    # 兼容当前项目使用的字典结果。
    if isinstance(result, dict):
        interrupts = result.get(
            "__interrupt__",
            (),
        )

        if interrupts:
            return get_interrupt_value(
                interrupts[0]
            )

    return None


def find_pending_interrupt(
    graph: Any,
    config: dict[str, Any],
) -> Any | None:
    """从已保存的 Graph 状态中查找审批中断。"""

    snapshot = graph.get_state(
        config
    )

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
            return get_interrupt_value(
                task_interrupts[0]
            )

    return None


def normalize_approval_request(
    value: Any,
) -> dict[str, Any]:
    """确保审批请求可以作为 JSON 返回。"""

    if isinstance(value, dict):
        return value

    return {
        "kind": "tool_approval",
        "tool_name": "unknown",
        "message": str(value),
        "arguments": {},
    }