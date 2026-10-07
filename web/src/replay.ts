// 실험 재생 — 하네스 본실험 원장을 내보낸 JSON(public/replays/*.json)을 두 줄로 재생하는 계산.
// 두 줄은 같은 박자(tick)로 한 행동씩 나아간다. 과제를 먼저 끝낸 줄은 다음 과제로, 전부 끝낸 줄은 기다린다.
export interface Bi { en: string; ko: string | null }
export interface Cite { id: string; title: string; excerpt: string }
export type ReplayAction =
  | { seq: number; kind: "consult"; question: Bi; answer: Bi; cited: Cite[] }
  | { seq: number; kind: "experiment"; note: Bi; parameters: Record<string, number | string>;
      results: { yield: number; ton: number } | null; success: boolean };
export interface ReplayEpisode {
  task_id: string; outcome: string | null; actions_to_success: number | null; actions: ReplayAction[];
}
export interface ReplayCondition {
  name: string;
  summary: { success: number; actions: number; consults: number; experiments: number };
  episodes: ReplayEpisode[];
}
export interface ReplayTask { task_id: string; title: string; targets: { yield?: number; ton?: number } }
export interface Replay {
  run_id: string; label: string; date: string; action_budget: number | null;
  tasks: ReplayTask[]; conditions: Record<string, ReplayCondition>;
}
export type Lang = "ko" | "en";

export interface Step { taskIndex: number; episodeIndex: number; action: ReplayAction }
export interface Lane {
  taskIndex: number;           // 지금 보여 줄 과제
  current: ReplayAction[];     // 그 과제에서 지금까지 나온 행동
  doneTasks: number;           // 모든 행동이 나온 과제 수
  finished: boolean;           // 이 줄의 행동이 모두 나왔다
  counts: { actions: number; consults: number; experiments: number };
}

export function flatten(cond: ReplayCondition, tasks: ReplayTask[]): Step[] {
  return cond.episodes.flatMap((ep, episodeIndex) => {
    const t = tasks.findIndex((x) => x.task_id === ep.task_id);
    const taskIndex = t >= 0 ? t : episodeIndex;
    return ep.actions.map((action) => ({ taskIndex, episodeIndex, action }));
  });
}

export function totalTicks(rep: Replay): number {
  return Math.max(0, ...Object.values(rep.conditions).map((c) => flatten(c, rep.tasks).length));
}

export function laneAt(cond: ReplayCondition, tasks: ReplayTask[], tick: number): Lane {
  const steps = flatten(cond, tasks);
  const shown = steps.slice(0, Math.max(0, tick));
  const last = shown[shown.length - 1];
  const episodeIndex = last ? last.episodeIndex : 0;
  const doneTasks = cond.episodes.filter((ep, i) =>
    shown.filter((s) => s.episodeIndex === i).length === ep.actions.length && ep.actions.length > 0).length;
  return {
    taskIndex: last ? last.taskIndex : 0,
    current: shown.filter((s) => s.episodeIndex === episodeIndex).map((s) => s.action),
    doneTasks,
    finished: shown.length >= steps.length,
    counts: {
      actions: shown.length,
      consults: shown.filter((s) => s.action.kind === "consult").length,
      experiments: shown.filter((s) => s.action.kind === "experiment").length,
    },
  };
}

// 과제 안에서 지금까지의 최고 수율·TON — 목표 대비 게이지에 쓴다
export function bestSoFar(actions: ReplayAction[]): { yield: number; ton: number } {
  const best = { yield: 0, ton: 0 };
  for (const a of actions) {
    if (a.kind === "experiment" && a.results) {
      best.yield = Math.max(best.yield, a.results.yield);
      best.ton = Math.max(best.ton, a.results.ton);
    }
  }
  return best;
}

export function text(b: Bi, lang: Lang): string {
  return lang === "ko" ? (b.ko ?? b.en) : b.en;
}
