import { describe, expect, it } from "vitest";
import { bannerKey, cardLink, modeNote } from "./ask";
import type { AskResult } from "./types";

const base: AskResult = { answer: "", evidence: "records", records: [], wiki: [] };

describe("ask helpers", () => {
  it("maps the legacy wiki label to knowledge", () => {
    expect(bannerKey("wiki")).toBe("knowledge");
    expect(bannerKey("records")).toBe("records");
    expect(bannerKey("none")).toBe("none");
  });

  it("links record cards to notes only", () => {
    const card = { id: "rec:r1", kind: "rec", title: "", text: "", source: { record_id: "r1" } };
    expect(cardLink(card)).toBe("/notes/r1");
    expect(cardLink({ ...card, id: "wiki:equipment/x", kind: "wiki", source: { wiki: "equipment/x" } })).toBeNull();
  });

  it("describes partial and unseen modes", () => {
    expect(modeNote({ ...base, mode: "partial", unknown: ["SPhos Pd G4"] })).toContain("SPhos Pd G4");
    expect(modeNote({ ...base, mode: "unseen" })).toContain("없는 질문");
    expect(modeNote({ ...base, mode: "seen" })).toBeNull();
    expect(modeNote(base)).toBeNull();
  });
});
