# Tech stack

- `backend/`: FastAPI and SQLite. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount. The database keeps runs, their to-do lists, an attempt count on each claim, and both the policy wording and the claims manual. Read operations include `health`, `list_claims`, `get_claim`, `get_policy`, `get_claim_history`, `list_handlers`, `list_steps`, `get_instructions`, `get_queue_instructions`, `get_sections`, `get_current_run`. Workflow operations include `start_claim`, `record_step`, `record_decision`, `pay_claim`, `sign_off_claim`, `start_run`, `add_todo`, `update_todo`, `finish_run`, `record_failure`.
- `agent/`: LangChain's `create_agent` on OpenRouter. `uv run -m agent` starts one run that works the queue with a to-do list and a fresh claim helper per claim; `uv run -m agent --cap 5` caps a trial at five claims; `uv run -m agent CLM-1001` works one claim. The default model is `deepseek/deepseek-v4.1-flash` with low reasoning effort, overridden by `MODEL_NAME`. The agent reaches claims, sections and its instructions only through the backend's API. A failed claim goes back in the queue; after two failures it is left for a handler.
- `dashboard/`: React, Vite and TypeScript. The queue shows the current run's to-do list and claims left for a handler; a claim shows the agent's steps, including the sections it read; the instructions page shows both sets of instructions.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from. The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. The OpenRouter key is `OPENROUTER_API_KEY` in `.env`.
