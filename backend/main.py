"""The UnderCover backend."""

import json
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException

from backend.database import connect, database_path, seed
from backend.models import (
    Claim,
    ClaimSummary,
    Decision,
    DecisionRequest,
    FailureRequest,
    FinishRequest,
    Handler,
    Instructions,
    Payment,
    PaymentRequest,
    Policy,
    PreviousClaim,
    Run,
    Sections,
    SignOffRequest,
    StartRequest,
    StartRunRequest,
    Step,
    StepRequest,
    Todo,
    TodoRequest,
    TodoStatusRequest,
)

INSTRUCTIONS = Path(__file__).parent / "instructions.md"
QUEUE_INSTRUCTIONS = Path(__file__).parent / "queue_instructions.md"
MAX_ATTEMPTS = 2


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed the database on startup if it doesn't exist yet."""
    if not database_path().exists():
        seed(database_path())
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)


def database() -> Iterator[sqlite3.Connection]:
    """Open the database for one request and commit if the request succeeds."""
    with closing(connect()) as connection, connection:
        yield connection


Database = Annotated[sqlite3.Connection, Depends(database)]


def now() -> str:
    """Return the current time in UTC, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def dollars(amount: float) -> str:
    """Format an amount like $1,250.00."""
    return f"${amount:,.2f}"


def approval_limit(db: sqlite3.Connection) -> float:
    """Return the largest payout that can be paid without a handler's sign-off."""
    return db.execute("SELECT payout_approval_limit FROM settings").fetchone()[0]


def sections(text: str, names: str) -> list[str]:
    """Return only the named sections of a document, with their headings."""
    wanted = {name.strip() for name in names.split(",") if name.strip()}
    parts = text.split("\n## ")
    return [
        "## " + part.strip()
        for part in parts[1:]
        if part.split("\n")[0].strip() in wanted
    ]


def to_todo(row: sqlite3.Row) -> Todo:
    """Build a to-do item from its row."""
    return Todo(**dict(row))


def to_run(db: sqlite3.Connection, row: sqlite3.Row) -> Run:
    """Build a run from its row, with its to-do items in order."""
    todos = db.execute(
        "SELECT * FROM todos WHERE run_id = ? ORDER BY todo_id", (row["run_id"],)
    ).fetchall()
    return Run(**dict(row), todos=[to_todo(todo) for todo in todos])


def current_run(db: sqlite3.Connection) -> sqlite3.Row:
    """Return the latest run, or raise a 404."""
    row = db.execute("SELECT * FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    if row is None:
        raise HTTPException(404, "No run has started")
    return row


def find_claim(db: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    """Return one claim's row, or raise a 404."""
    row = db.execute(
        "SELECT * FROM claim_view WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Claim {claim_id} not found")
    return row


def to_summary(row: sqlite3.Row) -> ClaimSummary:
    """Build a claim's line in the queue from its row."""
    return ClaimSummary(
        **json.loads(row["record"])
        | {
            "status": row["status"],
            "customer_name": row["customer_name"],
            "decision": row["decision"],
            "payout": row["payout"],
            "attempts": row["attempts"],
        }
    )


def to_claim(row: sqlite3.Row) -> Claim:
    """Build a claim in full, with its decision and payment, from its row."""
    decision = None
    if row["decision"] is not None:
        decision = Decision(**{field: row[field] for field in Decision.model_fields})
    payment = None
    if row["paid_at"] is not None:
        payment = Payment(**{field: row[field] for field in Payment.model_fields})
    return Claim(
        **json.loads(row["record"])
        | {
            "status": row["status"],
            "customer_name": row["customer_name"],
            "thread_id": row["thread_id"],
            "decision": decision,
            "payment": payment,
            "attempts": row["attempts"],
        }
    )


def pay(
    db: sqlite3.Connection, claim_id: str, amount: float, signed_off_by: str | None
) -> Payment:
    """Record a payment on a claim."""
    payment = Payment(amount=amount, paid_at=now(), signed_off_by=signed_off_by)
    db.execute(
        "INSERT INTO payments VALUES (?, ?, ?, ?)",
        (claim_id, payment.amount, payment.paid_at, payment.signed_off_by),
    )
    return payment


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(db: Database) -> list[ClaimSummary]:
    """List every claim in the queue, in id order."""
    rows = db.execute("SELECT * FROM claim_view ORDER BY claim_id").fetchall()
    return [to_summary(row) for row in rows]


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, db: Database) -> Claim:
    """Get one claim in full: the story, the items claimed and the documents."""
    return to_claim(find_claim(db, claim_id))


@app.get("/api/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, db: Database) -> Policy:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    row = db.execute(
        "SELECT record FROM policies WHERE policy_id = ?", (policy_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return Policy(**json.loads(row["record"]))


@app.get("/api/customers/{customer_id}/claims", operation_id="get_claim_history")
def get_claim_history(customer_id: str, db: Database) -> list[PreviousClaim]:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    row = db.execute(
        "SELECT record FROM customers WHERE customer_id = ?", (customer_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Customer {customer_id} not found")
    return [
        PreviousClaim(**claim) for claim in json.loads(row["record"])["previous_claims"]
    ]


@app.get("/api/instructions", operation_id="get_instructions")
def get_instructions() -> Instructions:
    """Get the agent's instructions for working one claim."""
    return Instructions(text=INSTRUCTIONS.read_text(encoding="utf-8"))


@app.get("/api/instructions/queue", operation_id="get_queue_instructions")
def get_queue_instructions() -> Instructions:
    """Get the agent's instructions for working the queue."""
    return Instructions(text=QUEUE_INSTRUCTIONS.read_text(encoding="utf-8"))


@app.get("/api/sections", operation_id="get_sections")
def get_sections(names: str, db: Database) -> Sections:
    """Get only the named sections of the policy wording and the claims manual."""
    wording, manual = db.execute(
        "SELECT policy_wording, claims_manual FROM settings"
    ).fetchone()
    return Sections(wording=sections(wording, names), manual=sections(manual, names))


@app.get("/api/handlers", operation_id="list_handlers")
def list_handlers(db: Database) -> list[Handler]:
    """List the claims handlers."""
    rows = db.execute("SELECT * FROM handlers ORDER BY handler_id").fetchall()
    return [Handler(**dict(row)) for row in rows]


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, request: StartRequest, db: Database) -> Claim:
    """Start work on a waiting claim, which moves it to in progress."""
    if find_claim(db, claim_id)["status"] != "waiting":
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    db.execute(
        "UPDATE claims SET status = 'in_progress', thread_id = ? WHERE claim_id = ?",
        (request.thread_id, claim_id),
    )
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/steps", operation_id="record_step")
def record_step(claim_id: str, request: StepRequest, db: Database) -> Step:
    """Record one step of the agent's work on a claim."""
    thread_id = find_claim(db, claim_id)["thread_id"]
    if thread_id is None:
        raise HTTPException(409, f"Claim {claim_id} has not been started")
    row = db.execute(
        "INSERT INTO steps (claim_id, thread_id, kind, content, created_at)"
        " VALUES (?, ?, ?, ?, ?) RETURNING *",
        (claim_id, thread_id, request.kind, request.content, now()),
    ).fetchone()
    return Step(**dict(row))


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, db: Database) -> list[Step]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(db, claim_id)
    rows = db.execute(
        "SELECT * FROM steps WHERE claim_id = ? ORDER BY step_id", (claim_id,)
    ).fetchall()
    return [Step(**dict(row)) for row in rows]


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, request: DecisionRequest, db: Database) -> Claim:
    """Record the decision on a claim; an approval over the limit waits for sign-off."""
    claim = find_claim(db, claim_id)
    if claim["decision"] is not None:
        raise HTTPException(409, f"Claim {claim_id} has already been decided")
    if claim["status"] != "in_progress":
        raise HTTPException(409, f"Claim {claim_id} is not in progress")
    payout = round(request.payout, 2)
    held = request.decision == "approve" and payout > approval_limit(db)
    db.execute(
        "INSERT INTO decisions VALUES (?, ?, ?, ?, ?, ?)",
        (claim_id, request.decision, payout, request.section, request.reason, now()),
    )
    db.execute(
        "UPDATE claims SET status = ? WHERE claim_id = ?",
        ("waiting_for_sign_off" if held else "decided", claim_id),
    )
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, request: PaymentRequest, db: Database) -> Payment:
    """Pay an approved claim its payout, unless it needs a handler's sign-off."""
    claim = find_claim(db, claim_id)
    if claim["decision"] != "approve":
        raise HTTPException(409, f"Claim {claim_id} has not been approved")
    if claim["paid_at"] is not None:
        raise HTTPException(409, f"Claim {claim_id} has already been paid")
    if claim["status"] == "waiting_for_sign_off":
        raise HTTPException(
            403,
            f"A payout over {dollars(approval_limit(db))} needs a handler's sign-off",
        )
    if round(request.amount, 2) != claim["payout"]:
        raise HTTPException(
            422, f"The amount must be the approved payout of {dollars(claim['payout'])}"
        )
    return pay(db, claim_id, claim["payout"], None)


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(claim_id: str, request: SignOffRequest, db: Database) -> Claim:
    """Sign off a held payout as a handler, which pays it and decides the claim."""
    claim = find_claim(db, claim_id)
    if claim["status"] != "waiting_for_sign_off":
        raise HTTPException(409, f"Claim {claim_id} is not waiting for sign-off")
    row = db.execute(
        "SELECT * FROM handlers WHERE handler_id = ?", (request.handler_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Handler {request.handler_id} not found")
    handler = Handler(**dict(row))
    if not handler.can_approve_over_limit:
        raise HTTPException(
            403,
            f"{handler.name} can't sign off payouts over {dollars(approval_limit(db))}",
        )
    pay(db, claim_id, claim["payout"], handler.name)
    db.execute("UPDATE claims SET status = 'decided' WHERE claim_id = ?", (claim_id,))
    return to_claim(find_claim(db, claim_id))


@app.post("/api/runs", operation_id="start_run")
def start_run(request: StartRunRequest, db: Database) -> Run:
    """Start a run, capped at a number of claims; 0 means no cap."""
    run_id = str(uuid4())
    db.execute(
        "INSERT INTO runs (run_id, cap, started_at) VALUES (?, ?, ?)",
        (run_id, request.cap, now()),
    )
    return to_run(db, current_run(db))


@app.get("/api/runs/current", operation_id="get_current_run")
def get_current_run(db: Database) -> Run:
    """Get the current run with its to-do list."""
    return to_run(db, current_run(db))


@app.post("/api/runs/{run_id}/todos", operation_id="add_todo")
def add_todo(run_id: str, request: TodoRequest, db: Database) -> Todo:
    """Add one claim to a run's to-do list."""
    row = db.execute(
        "INSERT INTO todos (run_id, claim_id, status, content, updated_at)"
        " VALUES (?, ?, 'to_do', ?, ?) RETURNING *",
        (run_id, request.claim_id, request.content, now()),
    ).fetchone()
    return to_todo(row)


@app.post("/api/todos/{todo_id}", operation_id="update_todo")
def update_todo(todo_id: int, request: TodoStatusRequest, db: Database) -> Todo:
    """Move a to-do item to its next state."""
    row = db.execute(
        "UPDATE todos SET status = ?, updated_at = ? WHERE todo_id = ? RETURNING *",
        (request.status, now(), todo_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"To-do {todo_id} not found")
    return to_todo(row)


@app.post("/api/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: str, request: FinishRequest, db: Database) -> Run:
    """Finish a run with a short summary for the handlers."""
    row = db.execute(
        "UPDATE runs SET finished_at = ?, summary = ? WHERE run_id = ? RETURNING *",
        (now(), request.summary, run_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"Run {run_id} not found")
    return to_run(db, row)


@app.post("/api/claims/{claim_id}/failure", operation_id="record_failure")
def record_failure(claim_id: str, request: FailureRequest, db: Database) -> Claim:
    """Retry a failed claim, or leave it for a handler after two attempts."""
    claim = find_claim(db, claim_id)
    if claim["decision"] is not None:
        raise HTTPException(409, f"Claim {claim_id} has already been decided")
    attempts = claim["attempts"] + 1
    left = attempts >= MAX_ATTEMPTS
    db.execute(
        "UPDATE claims SET attempts = ?, status = ?, thread_id = NULL"
        " WHERE claim_id = ?",
        (attempts, "left_for_handler" if left else "waiting", claim_id),
    )
    db.execute(
        "INSERT INTO steps (claim_id, thread_id, kind, content, created_at)"
        " VALUES (?, ?, 'message', ?, ?)",
        (claim_id, claim["thread_id"] or "", request.reason, now()),
    )
    run_id = db.execute(
        "SELECT run_id FROM runs ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if run_id:
        db.execute(
            "UPDATE todos SET status = ? WHERE run_id = ? AND claim_id = ?",
            ("left_for_handler" if left else "to_do", run_id[0], claim_id),
        )
    return to_claim(find_claim(db, claim_id))
