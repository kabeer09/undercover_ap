from fastapi.testclient import TestClient


def start_claim(client: TestClient, claim_id: str, thread_id: str) -> None:
    response = client.post(
        f"/api/claims/{claim_id}/start", json={"thread_id": thread_id}
    )
    assert response.status_code == 200


def decide(client: TestClient, claim_id: str, payout: float) -> None:
    response = client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": "approve",
            "payout": payout,
            "section": "Section 5, Baggage and Personal Effects",
            "reason": "Covered by the wording.",
        },
    )
    assert response.status_code == 200


def test_start_run_and_todos(client):
    run = client.post("/api/runs", json={"cap": 5}).json()
    assert run["cap"] == 5
    assert run["todos"] == []
    assert run["finished_at"] is None

    for claim_id in ("CLM-1001", "CLM-1002"):
        todo = client.post(
            f"/api/runs/{run['run_id']}/todos",
            json={"claim_id": claim_id, "content": f"Decide {claim_id}"},
        ).json()
        assert todo["status"] == "to_do"
    assert [t["claim_id"] for t in client.get("/api/runs/current").json()["todos"]] == [
        "CLM-1001",
        "CLM-1002",
    ]

    changed = client.post("/api/todos/1", json={"status": "in_progress"}).json()
    assert changed["status"] == "in_progress"
    assert client.get("/api/runs/current").json()["todos"][0]["status"] == "in_progress"


def test_finish_run(client):
    run_id = client.post("/api/runs", json={"cap": 3}).json()["run_id"]
    finished = client.post(
        f"/api/runs/{run_id}/finish", json={"summary": "Three claims decided"}
    ).json()
    assert finished["summary"] == "Three claims decided"
    assert finished["finished_at"] is not None
    assert client.get("/api/runs/current").json()["summary"] == "Three claims decided"


def test_failure_retries_then_leaves_claim_for_a_handler(client):
    run_id = client.post("/api/runs", json={"cap": 2}).json()["run_id"]
    client.post(
        f"/api/runs/{run_id}/todos",
        json={"claim_id": "CLM-1001", "content": "Decide CLM-1001"},
    )
    start_claim(client, "CLM-1001", "thread-1")

    first = client.post(
        "/api/claims/CLM-1001/failure", json={"reason": "Model timed out"}
    ).json()
    assert first["status"] == "waiting"
    assert first["attempts"] == 1
    assert first["thread_id"] is None
    assert client.get("/api/runs/current").json()["todos"][0]["status"] == "to_do"

    start_claim(client, "CLM-1001", "thread-2")
    second = client.post(
        "/api/claims/CLM-1001/failure", json={"reason": "Model timed out again"}
    ).json()
    assert second["status"] == "left_for_handler"
    assert second["attempts"] == 2
    assert (
        client.get("/api/runs/current").json()["todos"][0]["status"]
        == "left_for_handler"
    )
    assert any(
        step["content"] == "Model timed out again"
        for step in client.get("/api/claims/CLM-1001/steps").json()
    )


def test_no_claim_is_decided_or_paid_twice(client):
    start_claim(client, "CLM-1001", "thread-1")
    decide(client, "CLM-1001", 420.0)
    assert (
        client.post("/api/claims/CLM-1001/payment", json={"amount": 420.0}).status_code
        == 200
    )

    assert (
        client.post(
            "/api/claims/CLM-1001/decision",
            json={
                "decision": "decline",
                "payout": 0,
                "section": "Section 9",
                "reason": "Excluded.",
            },
        ).status_code
        == 409
    )
    assert (
        client.post("/api/claims/CLM-1001/payment", json={"amount": 420.0}).status_code
        == 409
    )


def test_sections_are_looked_up_not_handed_whole(client):
    response = client.get(
        "/api/sections",
        params={"names": "5. Baggage and Personal Effects,7. Interpretation notes"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["wording"]) == 1
    assert data["wording"][0].startswith("## 5. Baggage and Personal Effects")
    assert len(data["manual"]) == 1
    assert data["manual"][0].startswith("## 7. Interpretation notes")
    assert "## 2. Trip Cancellation" not in str(data)


def test_instructions_come_from_the_documents_not_the_evaluations(client):
    queue = client.get("/api/instructions/queue").json()["text"]
    claim = client.get("/api/instructions").json()["text"]
    assert "work the queue" in queue
    assert "get_sections" in claim
    assert "the manual" in claim
    for text in (queue, claim):
        assert "handler's decision" not in text.lower()
        assert "CLM-1001  approve" not in text
