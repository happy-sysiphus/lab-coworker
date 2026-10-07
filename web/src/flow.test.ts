import { describe, expect, it } from "vitest";
import { CONNECTORS, STAGES, playState, routeOf, stageLabel } from "./flow";
import type { TraceEvent } from "./flow";

const ev = (seq: number, stage: string, status = "ok"): TraceEvent =>
  ({ run_id: "r", seq, ts: seq, stage, status, summary: stage, data: {}, ms: null });

// 백엔드가 남기는 단계 id 전체 (스펙 10.1 표) — 다이어그램에 상자가 하나씩 있어야 한다
const BACKEND_STAGES = [
  "common.select", "common.pull", "common.export",
  "p1.parse", "p1.save", "p1.wiki", "p1.text", "p1.clean", "p1.chunk",
  "p2.context", "p2.extract", "p2.normalize", "p2.evaluate", "p2.tool", "p2.research", "p2.candidates",
  "p2.approve", "p2.store",
  "p3.link", "p3.search", "p3.similar", "p3.integrate", "p3.evaluate", "p3.reformulate", "p3.tool", "p3.web",
  "p3.answer", "p3.verify", "fb.feedback",
];

describe("flow", () => {
  it("has one box per backend stage and connectors only between known boxes", () => {
    expect(BACKEND_STAGES.every((s) => STAGES.some((b) => b.id === s))).toBe(true);
    const ids = new Set(STAGES.map((b) => b.id));
    expect(CONNECTORS.every(([a, b]) => ids.has(a) && ids.has(b))).toBe(true);
    expect(stageLabel("p3.web")).toBe("웹 검색");
    expect(stageLabel("unknown.stage")).toBe("unknown.stage");
  });

  it("lights boxes up to the step and counts each connector traversal", () => {
    const events = ["p3.link", "p3.search", "p3.integrate", "p3.evaluate", "p3.reformulate", "p3.tool",
      "p3.search", "p3.integrate", "p3.evaluate", "p3.answer", "p3.verify"].map((s, i) => ev(i + 1, s, s === "p3.evaluate" && i === 3 ? "fail" : "ok"));
    const st = playState(events, 9);
    expect(st.current).toBe("p3.evaluate");
    expect(st.lit.get("p3.evaluate")).toBe("ok");          // 마지막 상태가 남는다
    expect(st.lit.has("p3.answer")).toBe(false);
    expect(st.edges.get("p3.search>p3.integrate")).toBe(2);
    expect(st.edges.get("p3.evaluate>p3.reformulate")).toBe(1);
    expect(st.edges.get("p3.tool>p3.search")).toBe(1);
    expect(playState(events, 0)).toMatchObject({ current: null });
  });

  it("ignores consecutive pairs that are not drawn as connectors", () => {
    const st = playState([ev(1, "p3.link"), ev(2, "p2.store")], 2);
    expect(st.edges.size).toBe(0);
    expect(st.lit.size).toBe(2);
  });

  it("routes every connector inside the drawing", () => {
    for (const [a, b] of CONNECTORS) {
      const pts = routeOf(a, b);
      expect(pts.length).toBeGreaterThanOrEqual(2);
      expect(pts.every(([x, y]) => x >= 0 && x <= 1080 && y >= 0 && y <= 600)).toBe(true);
    }
  });
});
