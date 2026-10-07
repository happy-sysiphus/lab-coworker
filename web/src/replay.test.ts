import { describe, expect, it } from "vitest";
import { bestSoFar, flatten, laneAt, text, totalTicks } from "./replay";
import type { Replay, ReplayAction } from "./replay";

const exp = (seq: number, y: number, ton: number, success = false): ReplayAction => ({
  seq, kind: "experiment", note: { en: `note ${seq}`, ko: null },
  parameters: { catalyst: "SPhos Pd G3", temperature: 100, residence_time: 360, catalyst_loading: 1.2 },
  results: { yield: y, ton }, success,
});
const consult = (seq: number): ReplayAction => ({
  seq, kind: "consult", question: { en: "Q?", ko: "질문?" }, answer: { en: "A.", ko: null }, cited: [],
});

const rep: Replay = {
  run_id: "pilot-02", label: "본실험 v1", date: "2026-09-29", action_budget: 50,
  tasks: [{ task_id: "t1", title: "T1", targets: { yield: 70, ton: 60 } },
          { task_id: "t2", title: "T2", targets: { yield: 80, ton: 50 } }],
  conditions: {
    baseline: { name: "일반 LLM", summary: { success: 2, actions: 5, consults: 1, experiments: 4 }, episodes: [
      { task_id: "t1", outcome: "success", actions_to_success: 3, actions: [consult(1), exp(2, 20, 15), exp(3, 75, 62, true)] },
      { task_id: "t2", outcome: "success", actions_to_success: 2, actions: [exp(1, 30, 20), exp(2, 85, 55, true)] }] },
    product: { name: "LAB GENE", summary: { success: 2, actions: 3, consults: 1, experiments: 2 }, episodes: [
      { task_id: "t1", outcome: "success", actions_to_success: 2, actions: [consult(1), exp(2, 72, 61, true)] },
      { task_id: "t2", outcome: "success", actions_to_success: 1, actions: [exp(1, 82, 52, true)] }] },
  },
};

describe("replay", () => {
  it("flattens episodes into one step list per lane with task indexes", () => {
    const steps = flatten(rep.conditions.baseline, rep.tasks);
    expect(steps.map((s) => [s.taskIndex, s.action.seq])).toEqual([[0, 1], [0, 2], [0, 3], [1, 1], [1, 2]]);
    expect(totalTicks(rep)).toBe(5);
  });

  it("advances both lanes on the same beat and lets the faster lane finish first", () => {
    const b = laneAt(rep.conditions.baseline, rep.tasks, 3);
    const p = laneAt(rep.conditions.product, rep.tasks, 3);
    expect([b.taskIndex, b.current.length, b.doneTasks, b.finished]).toEqual([0, 3, 1, false]);
    expect([p.taskIndex, p.current.length, p.doneTasks, p.finished]).toEqual([1, 1, 2, true]);
    expect(p.counts).toEqual({ actions: 3, consults: 1, experiments: 2 });
    expect(laneAt(rep.conditions.baseline, rep.tasks, 0)).toMatchObject({ taskIndex: 0, current: [], doneTasks: 0 });
    expect(laneAt(rep.conditions.baseline, rep.tasks, 99).counts.actions).toBe(5);
  });

  it("tracks the best yield and TON so far within a task", () => {
    const acts = rep.conditions.baseline.episodes[0].actions;
    expect(bestSoFar(acts.slice(0, 1))).toEqual({ yield: 0, ton: 0 });
    expect(bestSoFar(acts.slice(0, 2))).toEqual({ yield: 20, ton: 15 });
    expect(bestSoFar(acts)).toEqual({ yield: 75, ton: 62 });
  });

  it("falls back to the original text when Korean is missing", () => {
    expect(text({ en: "Q?", ko: "질문?" }, "ko")).toBe("질문?");
    expect(text({ en: "A.", ko: null }, "ko")).toBe("A.");
    expect(text({ en: "A.", ko: "답" }, "en")).toBe("A.");
  });
});
