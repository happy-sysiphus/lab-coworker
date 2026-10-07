import type { Question } from "./types";

// 승인 화면(/review)의 탭·문구·강조 계산. 화면 컴포넌트는 이 순수 함수만 부른다.
export const REVIEW_TABS = [
  { key: "relation", label: "관계" },
  { key: "spec", label: "수치·범위" },
  { key: "identity", label: "동일성" },
  { key: "new_term", label: "신규 용어" },
  { key: "conflict", label: "충돌" },
  { key: "held", label: "보류" },
  { key: "auto", label: "자동 승인" },
] as const;

export const KIND_KO: Record<string, string> = {
  equipment: "장비", material: "물질", technique: "기법", parameter: "파라미터", metric: "지표", cause: "원인",
};

export const REASONS = [
  { code: "direction", label: "방향 오류" },
  { code: "condition", label: "조건 누락" },
  { code: "quote", label: "원문 불일치" },
  { code: "target", label: "다른 대상" },
  { code: "other", label: "기타" },
];

export const PREDICATES = ["increases", "decreases", "promotes", "inhibits", "competes_with", "requires", "spec_range"];

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// 청크 원문에서 인용 구절을 찾아 나눈다. 공백·줄바꿈 차이는 무시한다.
export function highlight(text: string, quote: string): { text: string; mark: boolean }[] {
  const words = (quote ?? "").trim().split(/\s+/).filter(Boolean).map(escapeRe);
  const m = words.length ? new RegExp(words.join("\\s+"), "i").exec(text) : null;
  if (!m) return [{ text, mark: false }];
  return [
    { text: text.slice(0, m.index), mark: false },
    { text: m[0], mark: true },
    { text: text.slice(m.index + m[0].length), mark: false },
  ].filter((p) => p.mark || p.text.length > 0);
}

// 이 답이 만들 노드·엣지를 한 줄로 미리 보여 준다
export function preview(q: Question): string {
  const r = q.recommended ?? {};
  if (["relation", "spec", "held", "conflict"].includes(q.kind)) {
    const c = r.claim ?? {};
    return `${c.subject} —${c.predicate}→ ${c.object} 클레임을 claims.yaml에 씁니다`;
  }
  if (q.kind === "new_term") {
    const nt = r.new_term ?? {};
    return `새 ${KIND_KO[nt.kind] ?? nt.kind} 용어 '${nt.label}'(상위 ${nt.parent ?? "없음"})를 overlay.yaml에 등록하고 등장 ${q.count}곳을 잇습니다`;
  }
  if (q.kind === "identity" || q.kind === "cause_label") {
    return `'${q.context?.surface}'을 ${r.term_id}의 별칭으로 overlay.yaml에 씁니다`;
  }
  return "";
}

export function completion(t: { open: number; answered: number }): number {
  const total = t.open + t.answered;
  return total ? Math.round((t.answered / total) * 100) : 0;
}
