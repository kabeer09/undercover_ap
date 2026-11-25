import sqlite3
from contextlib import closing

import pytest
from langchain_core.messages import AIMessage

from agent import __main__ as cli
from agent import main
from agent.tests.test_agent import StubModel, call


@pytest.fixture
def three_waiting(database):
    """Leave only CLM-1001, CLM-1002 and CLM-1003 waiting in the queue."""
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "UPDATE claims SET status = 'decided'"
            " WHERE claim_id NOT IN ('CLM-1001', 'CLM-1002', 'CLM-1003')"
        )


def decide(client, claim_id, payout=0):
    client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "thread"})
    client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": "decline",
            "payout": payout,
            "section": "Section 9",
            "reason": "Excluded.",
        },
    )


def queue_stub(*messages):
    return StubModel(
        messages=iter([*messages, AIMessage(content="Finished the queue.")])
    )


def test_run_queue_with_a_cap(monkeypatch, capsys, client, three_waiting):
    stub = queue_stub(
        call("list_claims"),
        call("add_todo", claim_id="CLM-1001", content="Decide CLM-1001"),
        call("work_claim", claim_id="CLM-1001"),
        call("add_todo", claim_id="CLM-1002", content="Decide CLM-1002"),
        call("work_claim", claim_id="CLM-1002"),
    )
    worked = []

    def work(claim_id, llm=None):
        worked.append(claim_id)
        decide(client, claim_id)
        main.set_todo(claim_id, "done")
        return f"{claim_id} decline $0.00"

    monkeypatch.setattr(main, "work_claim", work)
    summary = main.run_queue(2, stub)

    assert worked == ["CLM-1001", "CLM-1002"]
    assert "Finished the queue." in summary
    assert capsys.readouterr().out.startswith("Finished the queue.")
    waiting = [
        claim["claim_id"]
        for claim in client.get("/api/claims").json()
        if claim["status"] == "waiting"
    ]
    assert waiting == ["CLM-1003"]
    run = client.get("/api/runs/current").json()
    assert run["cap"] == 2
    assert [todo["status"] for todo in run["todos"]] == ["done", "done"]
    assert run["summary"] == summary
    assert run["finished_at"] is not None


def test_a_failed_claim_does_not_stop_the_run(monkeypatch, client, three_waiting):
    stub = queue_stub(
        call("add_todo", claim_id="CLM-1001", content="Decide CLM-1001"),
        call("work_claim", claim_id="CLM-1001"),
        call("add_todo", claim_id="CLM-1002", content="Decide CLM-1002"),
        call("work_claim", claim_id="CLM-1002"),
    )

    def work(claim_id, llm=None):
        if claim_id == "CLM-1001":
            client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "t"})
            client.post(
                f"/api/claims/{claim_id}/failure", json={"reason": "Model timed out"}
            )
            return "CLM-1001 failed: Model timed out"
        decide(client, claim_id)
        return f"{claim_id} decline $0.00"

    monkeypatch.setattr(main, "work_claim", work)
    main.run_queue(2, stub)

    claims = {c["claim_id"]: c for c in client.get("/api/claims").json()}
    assert claims["CLM-1001"]["status"] == "waiting"
    assert claims["CLM-1001"]["attempts"] == 1
    assert claims["CLM-1002"]["status"] == "decided"
    assert claims["CLM-1003"]["status"] == "waiting"


def test_failed_claim_is_retried_and_twice_is_left_for_a_handler(
    monkeypatch, client, three_waiting
):
    stub = queue_stub(
        call("add_todo", claim_id="CLM-1001", content="Decide CLM-1001"),
        call("work_claim", claim_id="CLM-1001"),
    )

    def work(claim_id, llm=None):
        claim = client.get(f"/api/claims/{claim_id}").json()
        if claim["status"] == "waiting":
            client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "t"})
        client.post(
            f"/api/claims/{claim_id}/failure", json={"reason": "Model timed out"}
        )
        return f"{claim_id} failed"

    monkeypatch.setattr(main, "work_claim", work)
    main.run_queue(1, stub)

    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["attempts"] == 1
    assert claim["status"] == "waiting"

    stub2 = queue_stub(
        call("add_todo", claim_id="CLM-1001", content="Decide CLM-1001"),
        call("work_claim", claim_id="CLM-1001"),
    )
    monkeypatch.setattr(main, "work_claim", work)
    main.run_queue(1, stub2)
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["attempts"] == 2
    assert claim["status"] == "left_for_handler"
    assert (
        client.get("/api/runs/current").json()["todos"][0]["status"]
        == "left_for_handler"
    )


def test_missed_claims_are_worked_before_the_run_finishes(
    monkeypatch, client, three_waiting
):
    stub = queue_stub(call("work_claim", claim_id="CLM-1001"))
    worked = []

    def work(claim_id, llm=None):
        worked.append(claim_id)
        decide(client, claim_id)
        return f"{claim_id} decline $0.00"

    monkeypatch.setattr(main, "work_claim", work)
    main.run_queue(3, stub)

    assert worked == ["CLM-1001", "CLM-1002", "CLM-1003"]
    assert all(
        claim["status"] == "decided"
        for claim in client.get("/api/claims").json()
        if claim["claim_id"] in worked
    )


def test_one_claim_is_never_decided_twice(client, three_waiting):
    decide(client, "CLM-1001")
    assert (
        client.post(
            "/api/claims/CLM-1001/decision",
            json={
                "decision": "refer",
                "payout": 0,
                "section": "Section 9",
                "reason": "Needs a colleague.",
            },
        ).status_code
        == 409
    )


def test_command_line_cap(monkeypatch):
    caps = []
    monkeypatch.setattr(cli, "run_queue", lambda cap=0: caps.append(cap))
    cli.main(["--cap", "5"])
    cli.main([])
    assert caps == [5, 0]
