import { useEffect, useMemo, useState } from "react";
import { Pause, Play, RotateCcw, StepForward } from "lucide-react";
import { api } from "../api";
import { BOX_H, CONNECTORS, KIND_LABEL, LOOPS, STAGES, STATUS_LABEL, playState, routeOf, stageLabel } from "../flow";
import type { PlayState, StageBox, TraceEvent, TraceRun } from "../flow";

const STEP_MS = 800;     // 단계당 0.8초
const POLL_MS = 1500;    // 진행 중 실행은 1.5초마다 이어 받는다
const MAX_WAIT = 40;     // 아직 시작 전인 실행 id를 기다리는 횟수

const PHASES = [
  { x: 15, y: 92, w: 180, h: 392, title: "Phase 1 · 자료 구조화" },
  { x: 338, y: 92, w: 387, h: 490, title: "Phase 2 · 온톨로지 에이전트" },
  { x: 745, y: 92, w: 330, h: 380, title: "Phase 3 · 리서치 에이전트" },
];
const TONE: Record<string, { fill: string; stroke: string; dot: string }> = {
  ok: { fill: "#eff6ff", stroke: "#3b82f6", dot: "bg-blue-500" },
  fail: { fill: "#fef2f2", stroke: "#ef4444", dot: "bg-red-500" },
  info: { fill: "#fffbeb", stroke: "#f59e0b", dot: "bg-amber-500" },
  skip: { fill: "#f1f5f9", stroke: "#94a3b8", dot: "bg-slate-400" },
};

const when = (ts: number) =>
  new Date(ts * 1000).toLocaleString("ko-KR", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

export default function RunsView({ initialRun }: { initialRun: string | null }) {
  const [runs, setRuns] = useState<TraceRun[]>([]);
  const [sel, setSel] = useState<string | null>(initialRun);
  const [run, setRun] = useState<TraceRun | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => api.flowRuns()
      .then((r) => { if (alive) { setRuns(r.runs); setSel((s) => s ?? r.runs[0]?.run_id ?? null); } })
      .catch((e) => alive && setError((e as Error).message));
    load();
    const t = setInterval(load, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // 고른 실행을 처음부터 재생한다. 진행 중이면 after=<마지막 seq>로 이어 받는다
  useEffect(() => {
    if (!sel) return;
    let alive = true;
    let last = 0;
    let waits = 0;
    let timer: number | undefined;
    setRun(null); setEvents([]); setStep(0); setPlaying(true);
    const pull = () => api.flowRun(sel, last)
      .then((r) => {
        if (!alive) return;
        setRun(r.run);
        if (r.events.length) {
          last = r.events[r.events.length - 1].seq;
          setEvents((ev) => [...ev, ...r.events]);
        }
        if (r.run.status === "running") timer = window.setTimeout(pull, POLL_MS);
      })
      .catch(() => { if (alive && ++waits < MAX_WAIT) timer = window.setTimeout(pull, POLL_MS); });
    pull();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [sel]);

  useEffect(() => {
    if (!playing || step >= events.length) return;
    const t = setTimeout(() => setStep((s) => s + 1), STEP_MS / speed);
    return () => clearTimeout(t);
  }, [playing, step, events.length, speed]);

  const st = useMemo(() => playState(events, step), [events, step]);
  const btn = "flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-sm";

  return (
    <div className="flex flex-col gap-4 p-4 md:flex-row md:p-6">
      <div className="hidden min-w-0 flex-1 md:block">
        <Diagram st={st} />
        <div className="mt-2 flex flex-wrap gap-3 text-xs text-slate-500">
          <span className="flex items-center gap-1"><i className="inline-block h-0.5 w-5 bg-blue-500" />이번 실행이 지난 길</span>
          <span className="flex items-center gap-1"><i className="inline-block h-0.5 w-5 bg-orange-500" />되먹임 루프</span>
          <span>×N은 같은 길을 지난 횟수입니다.</span>
        </div>
      </div>
      <aside className="w-full space-y-4 md:w-96 md:shrink-0">
        <section className="rounded-2xl border border-slate-200 bg-white">
          <div className="border-b border-slate-100 px-4 py-2 text-sm font-semibold">실행 기록</div>
          {error && <div className="p-4 text-sm text-red-600">불러오지 못했습니다 — {error}</div>}
          {!error && runs.length === 0 && (
            <div className="p-4 text-sm text-slate-500">아직 실행 기록이 없습니다. 실험을 기록하거나 질문하면 여기에 쌓입니다.</div>
          )}
          <ul className="max-h-60 overflow-y-auto">
            {runs.map((r) => (
              <li key={r.run_id}>
                <button onClick={() => setSel(r.run_id)}
                  className={`flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-slate-50 ${sel === r.run_id ? "bg-blue-50" : ""}`}>
                  <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">{KIND_LABEL[r.kind] ?? r.kind}</span>
                  <span className="min-w-0 flex-1 truncate">{r.title}</span>
                  <span className={`shrink-0 text-xs ${r.status === "failed" ? "text-red-600" : r.status === "running" ? "text-blue-600" : "text-slate-400"}`}>
                    {STATUS_LABEL[r.status] ?? r.status}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        {sel && (
          <section className="rounded-2xl border border-slate-200 bg-white">
            <div className="space-y-2 border-b border-slate-100 px-4 py-3">
              <div className="text-sm font-semibold">{run ? `${KIND_LABEL[run.kind] ?? run.kind} · ${run.title}` : "불러오는 중…"}</div>
              {run && <div className="text-xs text-slate-400">{when(run.started_at)} · {STATUS_LABEL[run.status] ?? run.status}</div>}
              <div className="flex flex-wrap gap-1">
                <button onClick={() => { if (step >= events.length) setStep(0); setPlaying(!playing); }}
                  className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}>
                  {playing && step < events.length ? <Pause size={14} aria-hidden /> : <Play size={14} aria-hidden />}
                  {playing && step < events.length ? "일시정지" : "재생"}
                </button>
                <button onClick={() => { setPlaying(false); setStep((s) => Math.min(events.length, s + 1)); }}
                  className={`${btn} ring-1 ring-slate-200 hover:bg-slate-50`}><StepForward size={14} aria-hidden />한 단계</button>
                <button onClick={() => { setStep(0); setPlaying(true); }}
                  className={`${btn} ring-1 ring-slate-200 hover:bg-slate-50`}><RotateCcw size={14} aria-hidden />다시</button>
                {[1, 2, 4].map((s) => (
                  <button key={s} onClick={() => setSpeed(s)}
                    className={`${btn} ${speed === s ? "bg-slate-800 text-white" : "ring-1 ring-slate-200 hover:bg-slate-50"}`}>×{s}</button>
                ))}
              </div>
            </div>
            <ol className="max-h-[50vh] space-y-1 overflow-y-auto p-3">
              {events.slice(0, step).map((e, i) => (
                <li key={e.seq} className={`flex gap-2 rounded-lg px-2 py-1.5 text-sm ${i === step - 1 ? "bg-blue-50" : ""}`}>
                  <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${(TONE[e.status] ?? TONE.ok).dot}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <b className="font-medium">{stageLabel(e.stage)}</b>
                      {e.ms != null && <span className="shrink-0 text-xs tabular-nums text-slate-400">{(e.ms / 1000).toFixed(1)}s</span>}
                    </div>
                    <div className="break-words text-xs text-slate-500">{e.summary}</div>
                  </div>
                </li>
              ))}
              {run?.status === "running" && step >= events.length && (
                <li className="px-2 py-1.5 text-xs text-blue-600">다음 단계를 기다리는 중…</li>
              )}
            </ol>
          </section>
        )}
      </aside>
    </div>
  );
}

function Diagram({ st }: { st: PlayState }) {
  return (
    <svg viewBox="0 0 1080 600" className="w-full rounded-2xl border border-slate-200 bg-white" role="img"
      aria-label="LAB GENE 워크플로 다이어그램">
      <defs>
        {[["idle", "#cbd5e1"], ["lit", "#3b82f6"], ["loop", "#f97316"]].map(([k, c]) => (
          <marker key={k} id={`arrow-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill={c} />
          </marker>
        ))}
      </defs>
      {PHASES.map((p) => (
        <g key={p.title}>
          <rect x={p.x} y={p.y} width={p.w} height={p.h} rx={16} fill="#f8fafc" stroke="#e2e8f0" />
          <text x={p.x + 12} y={p.y + 17} fontSize={12} fontWeight={600} fill="#64748b">{p.title}</text>
        </g>
      ))}
      {CONNECTORS.map(([a, b]) => {
        const key = `${a}>${b}`;
        const n = st.edges.get(key) ?? 0;
        const loop = LOOPS.has(key);
        const pts = routeOf(a, b);
        const kind = n ? (loop ? "loop" : "lit") : "idle";
        const color = n ? (loop ? "#f97316" : "#3b82f6") : "#cbd5e1";
        const [lx, ly] = longestMid(pts);
        return (
          <g key={key}>
            <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke={color}
              strokeWidth={n ? 2.5 : 1.25} strokeDasharray={!n && loop ? "5 4" : undefined}
              markerEnd={`url(#arrow-${kind})`} />
            {n > 1 && (
              <g>
                <rect x={lx - 13} y={ly - 9} width={26} height={16} rx={8} fill={color} />
                <text x={lx} y={ly + 3} fontSize={10} fontWeight={700} fill="#fff" textAnchor="middle">×{n}</text>
              </g>
            )}
          </g>
        );
      })}
      {STAGES.map((b) => <Box key={b.id} b={b} status={st.lit.get(b.id)} current={st.current === b.id} />)}
    </svg>
  );
}

function longestMid(pts: [number, number][]): [number, number] {
  let best: [number, number] = pts[0];
  let len = -1;
  for (let i = 1; i < pts.length; i++) {
    const [x1, y1] = pts[i - 1];
    const [x2, y2] = pts[i];
    const d = Math.abs(x2 - x1) + Math.abs(y2 - y1);
    if (d > len) { len = d; best = [(x1 + x2) / 2, (y1 + y2) / 2]; }
  }
  return best;
}

function Box({ b, status, current }: { b: StageBox; status?: string; current: boolean }) {
  const tone = status ? TONE[status] ?? TONE.ok : null;
  return (
    <g>
      {current && <rect x={b.x - 4} y={b.y - 4} width={b.w + 8} height={BOX_H + 8} rx={13} fill="none"
        stroke={tone?.stroke ?? "#3b82f6"} strokeOpacity={0.35} strokeWidth={6} className="animate-pulse" />}
      <rect x={b.x} y={b.y} width={b.w} height={BOX_H} rx={10}
        fill={b.idle ? "#f8fafc" : tone?.fill ?? "#ffffff"} stroke={b.idle ? "#cbd5e1" : tone?.stroke ?? "#cbd5e1"}
        strokeWidth={current ? 2.5 : 1.5} strokeDasharray={b.idle ? "4 3" : undefined} />
      <text x={b.x + b.w / 2} y={b.y + (b.idle ? 19 : 27)} fontSize={13} textAnchor="middle"
        fill={b.idle ? "#94a3b8" : status ? "#0f172a" : "#475569"} fontWeight={status ? 600 : 400}>{b.label}</text>
      {b.idle && <text x={b.x + b.w / 2} y={b.y + 35} fontSize={10} textAnchor="middle" fill="#94a3b8">{b.idle}</text>}
    </g>
  );
}
