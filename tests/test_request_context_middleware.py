from uuid import UUID

from fastapi.testclient import (
    TestClient,
)

from app.api.server import create_app


class FakeGraph:
    """健康检查不需要真实Graph。"""


def test_response_contains_request_id(
) -> None:
    app = create_app(
        agent_graph=FakeGraph()
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health"
        )

    assert response.status_code == 200

    request_id = response.headers[
        "x-request-id"
    ]

    # 非法UUID会在这里抛出异常。
    UUID(request_id)


def test_valid_client_request_id_is_preserved(
) -> None:
    app = create_app(
        agent_graph=FakeGraph()
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health",
            headers={
                "X-Request-ID": (
                    "frontend-test-001"
                ),
            },
        )

    assert (
        response.headers["x-request-id"]
        == "frontend-test-001"
    )


def test_invalid_request_id_is_replaced(
) -> None:
    app = create_app(
        agent_graph=FakeGraph()
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/health",
            headers={
                "X-Request-ID": (
                    "../../unsafe"
                ),
            },
        )

    returned_request_id = (
        response.headers["x-request-id"]
    )

    assert (
        returned_request_id
        != "../../unsafe"
    )

    UUID(returned_request_id)