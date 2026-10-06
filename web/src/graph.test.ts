import { describe, expect, it } from "vitest";
import { toForceData } from "./graph";
import type { KgGraph } from "./types";

const g: KgGraph = {
  nodes: [
    { id: "exp:r1", kind: "experiment", label: "r1", label_ko: "", status: "verified", full: "r1", rec_ids: ["r1"] },
    { id: "lg:flow_reactor", kind: "equipment", label: "flow reactor", label_ko: "흐름 반응기",
      status: "verified", full: "flow reactor", rec_ids: ["r1"] },
    { id: "sym:low_value", kind: "symptom", label: "값이 낮음", label_ko: "", status: "verified",
      full: "값이 낮음", rec_ids: ["r1"] },
    { id: "tmp:material:xphospdg3", kind: "material", label: "XPhos Pd G3", label_ko: "", status: "temp",
      full: "XPhos Pd G3", rec_ids: ["r1"] },
  ],
  links: [
    { source: "exp:r1", target: "lg:flow_reactor", rel: "USES_EQUIPMENT", kind: "record" },
    { source: "exp:r1", target: "sym:low_value", rel: "EXHIBITS", kind: "record" },
    { source: "exp:r1", target: "tmp:material:xphospdg3", rel: "USES_MATERIAL", kind: "record" },
  ],
};

describe("toForceData", () => {
  it("drops hidden kinds and the links that touch them", () => {
    const d = toForceData(g, new Set(["symptom"]));
    expect(d.nodes.map((n) => n.id)).toEqual(["exp:r1", "lg:flow_reactor", "tmp:material:xphospdg3"]);
    expect(d.links.map((l) => l.rel)).toEqual(["USES_EQUIPMENT", "USES_MATERIAL"]);
  });

  it("builds adjacency in both directions", () => {
    const d = toForceData(g, new Set());
    expect([...d.adj.get("exp:r1")!].sort()).toEqual(["lg:flow_reactor", "sym:low_value", "tmp:material:xphospdg3"]);
    expect([...d.adj.get("lg:flow_reactor")!]).toEqual(["exp:r1"]);
  });

  it("copies nodes so force-graph mutation does not leak into state", () => {
    const d = toForceData(g, new Set());
    (d.nodes[0] as unknown as { x: number }).x = 5;
    expect((g.nodes[0] as unknown as { x?: number }).x).toBeUndefined();
  });
});
