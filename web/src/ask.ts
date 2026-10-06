import type { AskResult, EvidenceCard, Evidence } from "./types";

// 이전 버전 세션의 "wiki"는 지금의 knowledge(사례 없이 연구실 지식만)와 같다
export function bannerKey(e: AskResult["evidence"]): Evidence {
  return e === "wiki" ? "knowledge" : e;
}

export const CARD_KIND_LABEL: Record<string, string> = {
  rec: "사례", cause: "원인", clm: "관계", path: "경로", spec: "스펙",
  psg: "원문", wiki: "위키", fu: "후속", web: "웹",
};

export function cardLink(card: EvidenceCard): string | null {
  return card.source.record_id ? `/notes/${card.source.record_id}` : null;
}

export function modeNote(r: AskResult): string | null {
  if (r.mode === "partial") return `일부 대상(${(r.unknown ?? []).join(", ")})은 연구실 지식에 없습니다.`;
  if (r.mode === "unseen") return "연구실 기록과 지식에 없는 질문입니다.";
  return null;
}
