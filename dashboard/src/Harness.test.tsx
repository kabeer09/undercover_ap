import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import type { Run } from "./api";
import { App } from "./App";
import { stubApi, summary } from "./testing";

const run: Run = {
  run_id: "run-1",
  cap: 5,
  started_at: "2026-11-25T10:00:00+00:00",
  finished_at: null,
  summary: null,
  todos: [
    {
      todo_id: 1,
      run_id: "run-1",
      claim_id: "CLM-1002",
      status: "in_progress",
      content: "Decide CLM-1002",
      updated_at: "2026-11-25T10:01:00+00:00",
    },
    {
      todo_id: 2,
      run_id: "run-1",
      claim_id: "CLM-1003",
      status: "left_for_handler",
      content: "Decide CLM-1003",
      updated_at: "2026-11-25T10:02:00+00:00",
    },
  ],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

it("shows the current run's to-do list on the queue page", async () => {
  stubApi({
    "GET /api/claims": [summary],
    "GET /api/runs/current": run,
  });
  renderAt("/");
  expect(
    await screen.findByRole("heading", { name: "Agent's to-do list" }),
  ).toBeDefined();
  expect(screen.getByText("Decide CLM-1002")).toBeDefined();
  expect(screen.getByText("Decide CLM-1003")).toBeDefined();
  expect(screen.getAllByText("Left for handler")).toHaveLength(2);
});

it("counts claims left for a handler", async () => {
  stubApi({
    "GET /api/claims": [{ ...summary, status: "left_for_handler" }],
  });
  renderAt("/");
  expect(await screen.findByLabelText("Left for handler: 1")).toBeDefined();
});

it("shows the queue and claim instructions", async () => {
  stubApi({
    "GET /api/instructions": { text: "# UnderCover Agent: claim" },
    "GET /api/instructions/queue": { text: "# UnderCover Agent: queue" },
  });
  renderAt("/instructions");
  expect(await screen.findByText("# UnderCover Agent: claim")).toBeDefined();
  expect(screen.getByText("# UnderCover Agent: queue")).toBeDefined();
});
