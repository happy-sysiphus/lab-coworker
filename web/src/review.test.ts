import { describe, expect, it } from "vitest";
import { completion, highlight, preview, REVIEW_TABS } from "./review";
import type { Question } from "./types";

const q = (over: Partial<Question>): Question => ({
  qid: "q1", kind: "relation", tab: "relation", group_key: "k", item_ids: [], text: "t", recommended: {},
  options: [], context: {}, priority: 1, count: 1, status: "open", created_at: 0, ...over,
});

describe("review helpers", () => {
  it("has the seven tabs in the spec order", () => {
    expect(REVIEW_TABS.map((t) => t.key)).toEqual(["relation", "spec", "identity", "new_term", "conflict", "held", "auto"]);
  });

  it("splits the chunk text around the quote, ignoring whitespace differences", () => {
    const parts = highlight("Keep it cool.  The reactor must stay\nbelow 110 °C. Then rinse.", "The reactor must stay below 110 °C.");
    expect(parts.map((p) => p.mark)).toEqual([false, true, false]);
    expect(parts[1].text).toBe("The reactor must stay\nbelow 110 °C.");
    expect(highlight("abc", "zzz")).toEqual([{ text: "abc", mark: false }]);
  });

  it("previews what an answer will create", () => {
    expect(preview(q({ kind: "relation", recommended: { claim: {
      subject: "temperature", subject_id: "quantitykind:Temperature", predicate: "promotes",
      object: "protodeboronation", object_id: "lg:protodeboronation" } } })))
      .toBe("temperature —promotes→ protodeboronation 클레임을 claims.yaml에 씁니다");
    expect(preview(q({ kind: "new_term", count: 3, context: { surface: "SPhos Pd G4" },
      recommended: { new_term: { label: "SPhos Pd G4", kind: "material", parent: "lg:palladacycle_precatalyst" } } })))
      .toBe("새 물질 용어 'SPhos Pd G4'(상위 lg:palladacycle_precatalyst)를 overlay.yaml에 등록하고 등장 3곳을 잇습니다");
    expect(preview(q({ kind: "identity", context: { surface: "수율" }, recommended: { term_id: "lg:reaction_yield" } })))
      .toBe("'수율'을 lg:reaction_yield의 별칭으로 overlay.yaml에 씁니다");
  });

  it("computes tab completion as answered over answered plus open", () => {
    expect(completion({ open: 1, answered: 3 })).toBe(75);
    expect(completion({ open: 0, answered: 0 })).toBe(0);
  });
});
