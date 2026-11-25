# Status

The claims pilot in `docs/PLAN.md` is built, and the harness in `docs/HARNESS.md` is built on top of it: `docs/PLAN_HARNESS.md` has all five phases ticked off.

## Running it

- `npm run dev` starts the backend on port 8000 and the dashboard on http://localhost:5173.
- `uv run -m backend.seed` rebuilds the database from `data/`, putting every claim back in the queue.
- `uv run -m agent` starts one run that works every waiting claim, choosing their order, keeping a to-do list and finishing with a summary.
- `uv run -m agent --cap 5` does the same on five claims for a cheap trial, leaving the rest waiting.
- `uv run -m agent CLM-1001` works one claim; `MODEL_NAME` overrides the default model.

## Built

- `backend/`: SQLite database seeded from `data/` (never `data/evals/`). The pilot's claim, policy, customer, decision, payment and step operations remain. New tables hold runs, their to-do items and an attempt count per claim; `record_failure` returns a failed claim to the queue and leaves it for a handler after two attempts, and a claim can never be decided or paid twice. `get_sections` serves only the named sections of the policy wording and the claims manual, so the agent no longer receives whole documents. Instructions for the queue and for a claim come from `backend/queue_instructions.md` and `backend/instructions.md`, written from the wording and manual, not from the handlers' decisions.
- `agent/`: one run works the queue with a to-do list, a fresh claim helper per claim, and a check for waiting claims before it finishes. Each helper works one claim from a clean conversation, records every step, and replies with one line: the decision and payout, or what went wrong. A cap limits a trial to a number of claims. The default model is `deepseek/deepseek-v4.1-flash` with low reasoning effort, and `MODEL_NAME` still overrides it. Tests use a stub model and never call a provider.
- `dashboard/`: the queue shows state counts, the current run's to-do list and a line per claim, including claims left for a handler. A claim page shows the full claim, decision, payment and the agent's steps, including the sections it looked up. The instructions page shows both sets of instructions. Pages refresh every two seconds and follow `docs/BRAND.md` in light and dark mode.
- `e2e/`: Playwright tests of the pages, the agent's steps and handler sign-off, on their own ports and database.

## Checks

`npm run check` runs ruff, pyright and pytest with 80% coverage, then Prettier, ESLint, tsc and vitest with 80% coverage, then Playwright.

## Last live run

To be filled in after the capped run on the default model.
