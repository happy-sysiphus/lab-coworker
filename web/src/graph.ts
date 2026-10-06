import type { KgGraph, KgNode, KgNodeKind } from "./types";

// 그래프는 서버(kg.sqlite)가 만든다. 여기서는 화면 표시용 필터와 인접 맵만 계산한다.
export const KIND_LABEL: Record<KgNodeKind, string> = {
  experiment: "실험", equipment: "장비", material: "재료", technique: "기법", parameter: "파라미터",
  metric: "지표", cause: "원인", symptom: "증상", passage: "원문",
};
export const KIND_COLOR: Record<KgNodeKind, string> = {
  experiment: "#3b82f6", equipment: "#10b981", material: "#8b5cf6", technique: "#0ea5e9",
  parameter: "#64748b", metric: "#ec4899", cause: "#f59e0b", symptom: "#ef4444", passage: "#94a3b8",
};
export const KIND_CHIP: Record<KgNodeKind, string> = {
  experiment: "bg-blue-100 text-blue-700", equipment: "bg-emerald-100 text-emerald-700",
  material: "bg-violet-100 text-violet-700", technique: "bg-sky-100 text-sky-700",
  parameter: "bg-slate-200 text-slate-700", metric: "bg-pink-100 text-pink-700",
  cause: "bg-amber-100 text-amber-700", symptom: "bg-red-100 text-red-700", passage: "bg-slate-100 text-slate-500",
};
// 증상 노드는 모든 실험에 붙는 허브라 처음엔 숨긴다. 원문(passage)은 매뉴얼 구축 뒤에 생긴다
export const DEFAULT_HIDDEN: KgNodeKind[] = ["symptom", "passage"];

export interface ForceLink { source: string; target: string; rel: string }
export interface ForceData { nodes: KgNode[]; links: ForceLink[]; adj: Map<string, Set<string>> }

// force-graph는 넘긴 객체에 좌표를 덧쓰므로 사본을 넘긴다. adj는 호버 하이라이트용 인접 맵.
export function toForceData(g: KgGraph, hidden: ReadonlySet<KgNodeKind>): ForceData {
  const nodes = g.nodes.filter((n) => !hidden.has(n.kind));
  const ids = new Set(nodes.map((n) => n.id));
  const links = g.links.filter((l) => ids.has(l.source) && ids.has(l.target));
  const adj = new Map<string, Set<string>>();
  for (const l of links) {
    if (!adj.has(l.source)) adj.set(l.source, new Set());
    if (!adj.has(l.target)) adj.set(l.target, new Set());
    adj.get(l.source)!.add(l.target);
    adj.get(l.target)!.add(l.source);
  }
  return {
    nodes: nodes.map((n) => ({ ...n })),
    links: links.map((l) => ({ source: l.source, target: l.target, rel: l.rel })),
    adj,
  };
}
