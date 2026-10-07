// 워크플로 뷰 — 실행 기록(trace) 이벤트를 발표 다이어그램 배치 위에 재생하는 계산.
// 상자 좌표는 SVG viewBox(0 0 1080 640) 기준이다. 화면은 이 이벤트만 그리므로 실제 동작과 어긋날 수 없다.
export interface TraceEvent {
  run_id: string; seq: number; ts: number; stage: string; status: string;
  summary: string; data: Record<string, unknown>; ms: number | null;
}
export interface TraceRun {
  run_id: string; kind: string; title: string; status: string;
  started_at: number; ended_at: number | null; n_events?: number;
}
export type Phase = "common" | "p1" | "p2" | "p3" | "fb";
export interface StageBox {
  id: string; label: string; phase: Phase; x: number; y: number; w: number; idle?: string;
}

const W = 150;
const box = (id: string, label: string, phase: Phase, x: number, y: number, w = W, idle?: string): StageBox =>
  ({ id, label, phase, x, y, w, idle });

export const STAGES: StageBox[] = [
  box("common.select", "도메인·온톨로지 선택", "common", 30, 30),
  box("common.pull", "공통 온톨로지 (GitHub)", "common", 380, 30),
  box("common.export", "선택적 기여", "common", 760, 30),
  box("p1.parse", "로그 구조화·재질문", "p1", 30, 120),
  box("p1.save", "저장", "p1", 30, 182),
  box("p1.wiki", "위키 편찬", "p1", 30, 244),
  box("p1.text", "텍스트 추출", "p1", 30, 306),
  box("p1.clean", "정제", "p1", 30, 368),
  box("p1.chunk", "청킹·색인", "p1", 30, 430),
  box("p2.context", "기존 개념·관계", "p2", 380, 120),
  box("p2.extract", "추출", "p2", 380, 182),
  box("p2.normalize", "정규화", "p2", 380, 244),
  box("p2.evaluate", "품질 평가", "p2", 380, 306),
  box("p2.research", "근거 재탐색·용어 후보", "p2", 560, 244),
  box("p2.tool", "도구 선택", "p2", 560, 306),
  box("p2.candidates", "지식·확장 후보", "p2", 380, 368),
  box("p2.approve", "연구자 승인", "p2", 380, 430),
  box("p2.store", "지식 그래프 · 벡터 색인", "p2", 380, 520, 330),
  box("p3.link", "최신화·용어 연결", "p3", 760, 120),
  box("p3.search", "관계 검색", "p3", 760, 182),
  box("p3.similar", "유사도 검색", "p3", 930, 182, W, "질의 시 미사용"),
  box("p3.integrate", "근거 통합", "p3", 760, 244),
  box("p3.tool", "도구 선택", "p3", 930, 244),
  box("p3.evaluate", "품질 평가", "p3", 760, 306),
  box("p3.reformulate", "질문 재구성", "p3", 930, 306),
  box("p3.answer", "출처 답변", "p3", 760, 368),
  box("p3.web", "웹 검색", "p3", 930, 368),
  box("p3.verify", "출처 검증", "p3", 760, 430),
  box("fb.feedback", "피드백", "fb", 930, 520),
];

// 그리는 연결선 (from, to). 이벤트가 이 순서로 이어지면 강조하고 횟수를 붙인다.
export const CONNECTORS: [string, string][] = [
  ["common.select", "common.pull"], ["common.pull", "p2.context"], ["p2.store", "common.export"],
  ["p1.parse", "p1.save"], ["p1.save", "p1.wiki"], ["p1.wiki", "p2.normalize"],
  ["p1.save", "p1.text"], ["p1.text", "p1.clean"], ["p1.clean", "p1.chunk"], ["p1.chunk", "p2.context"],
  ["p2.context", "p2.extract"], ["p2.extract", "p2.normalize"], ["p2.normalize", "p2.evaluate"],
  ["p2.evaluate", "p2.tool"], ["p2.tool", "p2.research"], ["p2.research", "p2.normalize"],
  ["p2.research", "p2.extract"], ["p2.evaluate", "p2.candidates"], ["p2.candidates", "p2.approve"],
  ["p2.candidates", "p2.store"], ["p2.approve", "p2.store"], ["p2.approve", "p2.context"],
  ["p2.normalize", "p2.store"], ["p2.store", "p2.context"], ["p2.store", "p3.search"],
  ["p3.link", "p3.search"], ["p3.search", "p3.integrate"], ["p3.integrate", "p3.evaluate"],
  ["p3.evaluate", "p3.reformulate"], ["p3.reformulate", "p3.tool"], ["p3.tool", "p3.search"],
  ["p3.evaluate", "p3.answer"], ["p3.evaluate", "p3.web"], ["p3.web", "p3.answer"],
  ["p3.answer", "p3.verify"], ["p3.web", "p2.candidates"],
  ["fb.feedback", "p2.store"],
];
// 발표에서 짚는 되먹임 연결선
export const LOOPS = new Set(["p2.evaluate>p2.tool", "p2.approve>p2.context", "p3.web>p2.candidates",
  "fb.feedback>p2.store", "p3.evaluate>p3.reformulate"]);

export const BOX_H = 44;
type Pt = [number, number];
// 상자를 피해 가도록 손으로 정한 경로. 나머지는 같은 행·같은 열·꺾은선 규칙으로 계산한다
const CUSTOM: Record<string, Pt[]> = {
  "p1.save>p1.text": [[180, 204], [194, 204], [194, 328], [180, 328]],
  "p1.chunk>p2.context": [[180, 452], [280, 452], [280, 142], [380, 142]],
  "p2.research>p2.extract": [[635, 244], [635, 204], [530, 204]],
  "p2.candidates>p2.store": [[380, 390], [366, 390], [366, 536], [380, 536]],
  "p2.approve>p2.context": [[380, 452], [352, 452], [352, 134], [380, 134]],
  "p2.normalize>p2.store": [[380, 276], [359, 276], [359, 548], [380, 548]],
  "p2.store>p2.context": [[380, 528], [345, 528], [345, 126], [380, 126]],
  "p2.approve>p2.store": [[455, 474], [455, 520]],
  "p2.store>p3.search": [[650, 520], [650, 497], [735, 497], [735, 204], [760, 204]],
  "p2.store>common.export": [[690, 520], [690, 490], [745, 490], [745, 52], [760, 52]],
  "p3.tool>p3.search": [[930, 266], [920, 266], [920, 204], [910, 204]],
  "p3.evaluate>p3.web": [[910, 340], [920, 340], [920, 390], [930, 390]],
  "p3.web>p2.candidates": [[1005, 412], [1005, 505], [728, 505], [728, 400], [530, 400]],
};

export function routeOf(from: string, to: string): Pt[] {
  const custom = CUSTOM[`${from}>${to}`];
  if (custom) return custom;
  const a = STAGES.find((x) => x.id === from)!;
  const b = STAGES.find((x) => x.id === to)!;
  const mid = (x: StageBox): number => x.x + x.w / 2;
  const h = BOX_H / 2;
  if (a.y === b.y) return a.x < b.x ? [[a.x + a.w, a.y + h], [b.x, b.y + h]] : [[a.x, a.y + h], [b.x + b.w, b.y + h]];
  if (a.x === b.x) return a.y < b.y ? [[mid(a), a.y + BOX_H], [mid(b), b.y]] : [[mid(a), a.y], [mid(b), b.y + BOX_H]];
  const [sx, tx] = a.x < b.x ? [a.x + a.w, b.x] : [a.x, b.x + b.w];
  const mx = (sx + tx) / 2;
  return [[sx, a.y + h], [mx, a.y + h], [mx, b.y + h], [tx, b.y + h]];
}

export const KIND_LABEL: Record<string, string> = {
  record: "실험 기록", manual: "매뉴얼 구축", web_source: "웹 지식 후보", approval: "연구자 승인",
  ask: "질문", feedback: "피드백", ontology: "도메인·온톨로지", rebuild: "재구축",
};
export const STATUS_LABEL: Record<string, string> = {
  running: "진행 중", done: "완료", failed: "실패", paused: "일시정지",
};

export function stageLabel(id: string): string {
  return STAGES.find((b) => b.id === id)?.label ?? id;
}

export interface PlayState {
  lit: Map<string, string>;     // 켜진 상자 → 마지막 상태
  edges: Map<string, number>;   // "from>to" → 지나간 횟수
  current: string | null;       // 지금 단계
}

export function playState(events: TraceEvent[], upto: number): PlayState {
  const drawn = new Set(CONNECTORS.map(([a, b]) => `${a}>${b}`));
  const lit = new Map<string, string>();
  const edges = new Map<string, number>();
  const shown = events.slice(0, Math.max(0, upto));
  shown.forEach((e, i) => {
    lit.set(e.stage, e.status);
    const prev = shown[i - 1];
    const key = prev ? `${prev.stage}>${e.stage}` : "";
    if (prev && drawn.has(key)) edges.set(key, (edges.get(key) ?? 0) + 1);
  });
  return { lit, edges, current: shown.length ? shown[shown.length - 1].stage : null };
}
