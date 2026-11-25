# Plan: the agent's harness

From `docs/HARNESS.md`. The pilot is built; this plan grows it into an agent that runs the whole queue on its own, with a to-do list, a fresh helper per claim, section lookup, and automatic recovery from failure. `docs/PLAN.md` stays as it is.

## Phase 1: Runs, to-dos, retries and left-for-handler claims

The backend gains the state a run needs: a `runs` table (cap, start and finish times, summary), a `todos` table (one item per claim, with `to_do`, `in_progress`, `done` or `left_for_handler`), an `attempts` count on each claim, and the `left_for_handler` claim state. New operations follow the API rules: `start_run`, `get_current_run`, `add_todo`, `update_todo`, `finish_run`, `record_failure`. `record_failure` moves a failed claim back to the queue and leaves it for a handler after two attempts. `record_decision` and `pay_claim` refuse a second decision or payment.

- [x] Tables, migrations and models added; fresh seeding leaves 25 claims waiting with 0 attempts.
- [x] `uv run pytest -q backend` passes, with tests for start/run state, to-do updates, a claim going back to waiting on first failure, left for handler on the second, and no second decision or payment.
- [x] `uv run ruff check backend` and `pyright` pass.

## Phase 2: Sections of the wording and the manual

The database stores `claims_manual.md` alongside the policy wording. A `get_sections` operation takes comma-separated headings and returns only those sections of both documents. `get_instructions` keeps serving the claim instructions; `get_queue_instructions` serves the new queue instructions. Both are written from the wording and the manual, never from `data/evals/`. `docs/SPEC.md` drops "The claims manual" from Not for now.

- [x] `uv run pytest -q backend` passes, with tests that a section lookup returns only the named sections and that neither instructions endpoint contains a handler's decision.
- [x] `docs/SPEC.md` describes the manual as in use.

## Phase 3: The harness in the agent

`work_claim()` starts a fresh claim agent with claim-scoped tools and the claim instructions, records every step, and replies with one line. `run_queue(cap)` starts a run, lets the queue agent choose claims via `work_claim`, keep its to-do list, check for missed claims and finish with a summary. A failed claim is recorded as a failure and the run continues; the cap and missed-claim check are enforced. The default model becomes `deepseek/deepseek-v4.1-flash` with low reasoning effort, still overridden by `MODEL_NAME`. The CLI accepts `--cap N` and still takes one claim id.

- [x] `uv run pytest -q agent` passes with a stub model: a five-claim cap leaves the rest waiting, a failure does not stop the run, a failed claim returns to the queue and is retried, two failures leave it for a handler, no claim is decided twice, and the missed-claim check finds what is left.
- [x] Tests for the default model and `MODEL_NAME` override pass.
- [x] `uv run ruff check agent` and `pyright` pass.

## Phase 4: What handlers can see

The queue page shows the current run's to-do list, updating as items change, and counts claims left for a handler. The claim page shows the sections the agent looked up as steps, alongside the other steps. The instructions page shows both the queue and claim instructions. Styles follow `docs/BRAND.md` in light and dark mode.

- [x] `npx vitest run --root dashboard --coverage` passes with tests for the to-do list, the new state and the two instruction texts.
- [x] `npm run check:ts` passes.

## Phase 5: Live run and handover

Reseed, then run the agent on the default model capped at five claims. Check the decisions, the to-do list, the claim steps and the untouched waiting claims. Update `docs/TECH_STACK.md` and `docs/STATUS.md`.

- [ ] `uv run -m backend.seed`, then `uv run -m agent --cap 5` works five claims and leaves the rest waiting. Blocked: OpenRouter 402 credit limit after one claim.
- [ ] The queue shows the to-do list filled in and the claim pages show the sections read. Not checked live for the same reason.
- [x] `npm run check` is green: ruff, pyright, pytest with 80% coverage, ESLint, Prettier, tsc, vitest with 80% coverage, and Playwright.
- [x] `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` describe the product as it now is.

## Rules

Tests never call a model; the agent's tests use a stub. Every change is checked and committed. No AWS resources. Nothing here reads `data/evals/`.
