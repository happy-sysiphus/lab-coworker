import { useEffect, useRef, useState } from "react";
import { FlaskConical, Languages, Pause, Play, Quote, Repeat, RotateCcw, StepForward, Trophy } from "lucide-react";
import { bestSoFar, laneAt, text, totalTicks } from "../replay";
import type { Lane, Lang, Replay, ReplayAction, ReplayCondition, ReplayTask } from "../replay";

const STEP_MS = 1500;   // 한 박자 — 카드 글을 읽을 시간
const HOLD_MS = 9000;   // 반복 재생에서 비교 카드를 보여 주는 시간
const LANES: { key: string; tone: string; badge: string }[] = [
  { key: "baseline", tone: "border-slate-300", badge: "bg-slate-200 text-slate-700" },
  { key: "product", tone: "border-blue-300", badge: "bg-blue-600 text-white" },
];

export default function ReplayView() {
  const [rep, setRep] = useState<Replay | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loop, setLoop] = useState(false);
  const [lang, setLang] = useState<Lang>("ko");

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}replays/main-v1.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
      .then(setRep)
      .catch((e) => setError((e as Error).message));
  }, []);

  const total = rep ? totalTicks(rep) : 0;
  const ended = !!rep && tick >= total;

  useEffect(() => {
    if (!playing || !rep) return;
    if (tick >= total) {
      if (!loop) { setPlaying(false); return; }
      const t = setTimeout(() => setTick(0), HOLD_MS / speed);
      return () => clearTimeout(t);
    }
    const t = setTimeout(() => setTick((x) => x + 1), STEP_MS / speed);
    return () => clearTimeout(t);
  }, [playing, tick, total, speed, loop, rep]);

  if (error) return <div className="p-8 text-sm text-red-600">재생 데이터를 불러오지 못했습니다 — {error}</div>;
  if (!rep) return <div className="p-8 text-sm text-slate-500">재생 데이터를 불러오는 중…</div>;

  const btn = "flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm";
  return (
    <div className="space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center gap-2">
        <div className="mr-auto">
          <div className="font-bold">{rep.label} · {rep.date}</div>
          <div className="text-xs text-slate-500">
            같은 과제 {rep.tasks.length}개를 일반 LLM과 LAB GENE이 각각 풀었습니다. 한 박자에 한 행동씩 나란히 재생합니다.
          </div>
        </div>
        <button onClick={() => { if (ended) setTick(0); setPlaying(!playing); }}
          className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}>
          {playing ? <Pause size={16} aria-hidden /> : <Play size={16} aria-hidden />}{playing ? "일시정지" : "재생"}
        </button>
        <button onClick={() => { setPlaying(false); setTick((x) => Math.min(total, x + 1)); }}
          className={`${btn} bg-white ring-1 ring-slate-200 hover:bg-slate-50`}>
          <StepForward size={16} aria-hidden />한 단계
        </button>
        <button onClick={() => { setPlaying(false); setTick(0); }}
          className={`${btn} bg-white ring-1 ring-slate-200 hover:bg-slate-50`}>
          <RotateCcw size={16} aria-hidden />처음으로
        </button>
        <div className="flex overflow-hidden rounded-lg ring-1 ring-slate-200">
          {[1, 2, 4].map((s) => (
            <button key={s} onClick={() => setSpeed(s)}
              className={`px-2.5 py-1.5 text-sm ${speed === s ? "bg-slate-800 text-white" : "bg-white hover:bg-slate-50"}`}>
              ×{s}
            </button>
          ))}
        </div>
        <button onClick={() => setLoop(!loop)} aria-pressed={loop}
          className={`${btn} ${loop ? "bg-emerald-600 text-white" : "bg-white ring-1 ring-slate-200 hover:bg-slate-50"}`}>
          <Repeat size={16} aria-hidden />반복
        </button>
        <button onClick={() => setLang(lang === "ko" ? "en" : "ko")}
          className={`${btn} bg-white ring-1 ring-slate-200 hover:bg-slate-50`}>
          <Languages size={16} aria-hidden />{lang === "ko" ? "한국어" : "원문"}
        </button>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div className="h-full bg-blue-500 transition-all" style={{ width: `${total ? (tick / total) * 100 : 0}%` }} />
      </div>

      {ended && <Comparison rep={rep} />}

      <div className="grid gap-4 md:grid-cols-2">
        {LANES.filter((l) => rep.conditions[l.key]).map((l) => (
          <LaneView key={l.key} cond={rep.conditions[l.key]} tasks={rep.tasks} tick={tick} lang={lang}
            budget={rep.action_budget} tone={l.tone} badge={l.badge} />
        ))}
      </div>
    </div>
  );
}

function LaneView({ cond, tasks, tick, lang, budget, tone, badge }: {
  cond: ReplayCondition; tasks: ReplayTask[]; tick: number; lang: Lang; budget: number | null;
  tone: string; badge: string;
}) {
  const lane: Lane = laneAt(cond, tasks, tick);
  const task = tasks[lane.taskIndex];
  const best = bestSoFar(lane.current);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight, behavior: "smooth" });
  }, [lane.current.length, lane.taskIndex]);

  return (
    <section className={`flex flex-col rounded-2xl border-2 bg-white ${tone}`}>
      <div className="space-y-2 border-b border-slate-100 p-4">
        <div className="flex items-center justify-between">
          <span className={`rounded-full px-3 py-1 text-sm font-bold ${badge}`}>{cond.name}</span>
          <span className="text-sm text-slate-500">
            행동 <b className="text-slate-900">{lane.counts.actions}</b>{budget ? ` / ${budget}` : ""}
            {" · "}상담 {lane.counts.consults} · 실험 {lane.counts.experiments}
          </span>
        </div>
        <div className="flex gap-1">
          {tasks.map((t, i) => (
            <div key={t.task_id} title={t.title}
              className={`h-2 flex-1 rounded-full ${i < lane.doneTasks ? "bg-emerald-500"
                : i === lane.taskIndex ? "bg-blue-400" : "bg-slate-200"}`} />
          ))}
        </div>
        {task && !lane.finished && (
          <div className="space-y-1">
            <div className="truncate text-xs text-slate-500">과제 {lane.taskIndex + 1} · {task.title}</div>
            <Gauge label="수율" unit="%" value={best.yield} target={task.targets.yield} />
            <Gauge label="TON" unit="" value={best.ton} target={task.targets.ton} />
          </div>
        )}
      </div>
      <div ref={list} className="h-[52vh] space-y-2 overflow-y-auto p-4">
        {lane.finished && tick > 0 ? (
          <div className="rounded-xl bg-emerald-50 p-4 text-center text-sm text-emerald-800">
            <Trophy className="mx-auto mb-1" size={22} aria-hidden />
            과제 {cond.summary.success}/{tasks.length}개 성공 · 총 행동 {cond.summary.actions}회
          </div>
        ) : (
          lane.current.map((a, i) => <ActionCard key={`${lane.taskIndex}-${i}`} a={a} lang={lang} />)
        )}
        {tick === 0 && <div className="pt-10 text-center text-sm text-slate-400">재생을 누르면 시작합니다.</div>}
      </div>
    </section>
  );
}

function Gauge({ label, unit, value, target }: { label: string; unit: string; value: number; target?: number }) {
  const pct = target ? Math.min(100, (value / target) * 100) : 0;
  const hit = !!target && value >= target;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-8 text-slate-500">{label}</span>
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full transition-all ${hit ? "bg-emerald-500" : "bg-amber-400"}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-28 text-right tabular-nums text-slate-600">
        {value.toFixed(1)}{unit} / 목표 {target?.toFixed(1) ?? "?"}{unit}
      </span>
    </div>
  );
}

function ActionCard({ a, lang }: { a: ReplayAction; lang: Lang }) {
  const [open, setOpen] = useState<string | null>(null);
  if (a.kind === "consult") {
    const cite = a.cited.find((c) => c.id === open);
    return (
      <div className="rounded-xl border border-violet-200 bg-violet-50/50 p-3">
        <div className="flex items-center gap-1 text-xs font-semibold text-violet-700"><Quote size={14} aria-hidden />상담</div>
        <div className="mt-1 text-sm font-medium">{text(a.question, lang)}</div>
        <div className="mt-1 whitespace-pre-line text-sm text-slate-600">{text(a.answer, lang)}</div>
        {a.cited.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {a.cited.map((c) => (
              <button key={c.id} onClick={() => setOpen(open === c.id ? null : c.id)}
                className={`max-w-full truncate rounded-full px-2 py-0.5 text-xs ${open === c.id
                  ? "bg-violet-600 text-white" : "bg-white text-violet-700 ring-1 ring-violet-200"}`}>
                {c.title}
              </button>
            ))}
          </div>
        )}
        {cite && <div className="mt-2 rounded-lg bg-white p-2 text-xs text-slate-600">{cite.excerpt || "발췌 없음"}</div>}
      </div>
    );
  }
  const p = a.parameters;
  return (
    <div className={`rounded-xl border p-3 ${a.success ? "border-emerald-300 bg-emerald-50" : "border-slate-200 bg-white"}`}>
      <div className="flex items-center justify-between text-xs">
        <span className="flex items-center gap-1 font-semibold text-slate-600"><FlaskConical size={14} aria-hidden />실험</span>
        {a.success && <span className="rounded-full bg-emerald-600 px-2 py-0.5 font-semibold text-white">목표 달성</span>}
      </div>
      {text(a.note, lang) && <div className="mt-1 line-clamp-3 text-sm text-slate-600">{text(a.note, lang)}</div>}
      <div className="mt-2 flex flex-wrap gap-1 text-xs">
        {[`${p.catalyst}`, `${p.temperature}°C`, `${p.residence_time}s`, `${p.catalyst_loading} mol%`].map((x) => (
          <span key={x} className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-700">{x}</span>
        ))}
      </div>
      {a.results && (
        <div className="mt-2 text-sm">
          수율 <b>{a.results.yield.toFixed(1)}%</b> · TON <b>{a.results.ton.toFixed(1)}</b>
        </div>
      )}
    </div>
  );
}

function Comparison({ rep }: { rep: Replay }) {
  const b = rep.conditions.baseline?.summary;
  const p = rep.conditions.product?.summary;
  if (!b || !p) return null;
  const rows: [string, number, number][] = [
    ["과제 성공", b.success, p.success], ["총 행동", b.actions, p.actions],
    ["상담", b.consults, p.consults], ["실험", b.experiments, p.experiments],
  ];
  const saved = b.actions - p.actions;
  return (
    <div className="rounded-2xl border-2 border-blue-200 bg-white p-4">
      <div className="mb-2 flex items-center gap-2 font-bold"><Trophy size={18} aria-hidden className="text-amber-500" />결과 비교</div>
      <table className="w-full text-sm">
        <thead><tr className="text-slate-500"><th className="text-left font-normal" /><th>일반 LLM</th><th>LAB GENE</th></tr></thead>
        <tbody>
          {rows.map(([k, x, y]) => (
            <tr key={k} className="border-t border-slate-100">
              <td className="py-1.5 text-slate-600">{k}</td>
              <td className="text-center tabular-nums">{k === "과제 성공" ? `${x}/${rep.tasks.length}` : x}</td>
              <td className="text-center font-semibold tabular-nums text-blue-700">{k === "과제 성공" ? `${y}/${rep.tasks.length}` : y}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {saved > 0 && (
        <div className="mt-2 text-sm text-slate-600">
          LAB GENE은 같은 과제를 행동 {saved}회 적게 써서 풀었습니다.
        </div>
      )}
    </div>
  );
}
