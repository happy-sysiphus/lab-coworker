import { useEffect, useRef, useState } from "react";
import { FileUp, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { MobileBar } from "../nav";
import { completion, highlight, KIND_KO, PREDICATES, preview, REASONS, REVIEW_TABS } from "../review";
import type { AutoItem, KgStatus, Question } from "../types";

// 승인 화면 — 온톨로지 에이전트가 만든 질문에 답한다. 답은 overlay·claims YAML에 쓰이고 그래프가 다시 계산된다.
const DOC_STATUS: Record<string, string> = {
  queued: "대기", running: "구축 중", paused: "일시정지", done: "완료", error: "오류",
};

export default function Review() {
  const nav = useNavigate();
  const [st, setSt] = useState<KgStatus | null>(null);
  const [tab, setTab] = useState<string>("relation");
  const [list, setList] = useState<Question[]>([]);
  const [auto, setAuto] = useState<AutoItem[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<Question | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [msg, setMsg] = useState<{ text: string; run?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rev, setRev] = useState(0);
  const refresh = () => setRev((r) => r + 1);

  useEffect(() => {
    let alive = true;
    const load = () => api.kgStatus().then((s) => alive && setSt(s)).catch((e) => alive && setError((e as Error).message));
    load();
    const t = setInterval(load, 4000);   // 구축은 백그라운드에서 돈다 — 진행률과 미답 수를 따라간다
    return () => { alive = false; clearInterval(t); };
  }, [rev]);

  useEffect(() => {
    api.questions(tab).then((r) => {
      setList(r.questions);
      setAuto(r.auto ?? []);
      setPicked([]);
      setSel((s) => (s && r.questions.some((q) => q.qid === s) ? s : r.questions[0]?.qid ?? null));
    }).catch((e) => setError((e as Error).message));
  }, [tab, rev, st?.open]);

  useEffect(() => {
    if (!sel) { setDetail(null); return; }
    api.question(sel).then(setDetail).catch(() => setDetail(null));
  }, [sel, rev]);

  async function act(action: string, reason?: string, edit?: Record<string, unknown>) {
    if (!detail) return;
    setError(null);
    try {
      const r = await api.answer(detail.qid, action, reason, edit);
      setMsg({ text: action === "skip" ? "건너뛰었습니다." : action === "hold" ? "보류 탭으로 옮겼습니다."
        : `${r.verdict === "verified" ? "승인" : "거절"}했습니다${r.wrote?.length ? ` — ${r.wrote.join(", ")}` : ""}.`, run: r.run_id });
      setSel(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="flex h-screen flex-col">
      <MobileBar title="검토" subtitle="지식 후보 승인" />
      <header className="hidden border-b border-slate-200 bg-white px-6 py-3 md:block">
        <div className="font-bold">검토</div>
        <div className="text-xs text-slate-400">
          온톨로지 에이전트가 매뉴얼과 기록에서 찾은 후보입니다. 승인한 것만 지식 그래프에 들어갑니다.
        </div>
      </header>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto bg-slate-50 p-4 md:p-6">
        <Sources st={st} onChange={refresh} onRun={(run) => nav(`/flow?run=${run}`)} />
        {error && <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}
        {msg && (
          <div className="rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
            {msg.text}{" "}
            {msg.run && <button onClick={() => nav(`/flow?run=${msg.run}`)} className="underline">워크플로에서 보기</button>}
          </div>
        )}
        <nav className="flex flex-wrap gap-1">
          {REVIEW_TABS.map((t) => {
            const counts = st?.tabs[t.key] ?? { open: 0, answered: 0 };
            return (
              <button key={t.key} onClick={() => { setTab(t.key); setSel(null); }}
                className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-sm ${tab === t.key ? "bg-slate-800 text-white" : "bg-white ring-1 ring-slate-200 hover:bg-slate-100"}`}>
                {t.label}
                <span className={`rounded-full px-1.5 text-xs ${tab === t.key ? "bg-white/20" : "bg-slate-100"}`}>{counts.open}</span>
                {t.key !== "auto" && counts.answered + counts.open > 0 && (
                  <span className="text-xs opacity-60">{completion(counts)}%</span>
                )}
              </button>
            );
          })}
        </nav>

        {tab === "auto" ? (
          <AutoList items={auto} onRevoke={async (id) => { await api.revoke(id); refresh(); }} />
        ) : (
          <div className="flex flex-col gap-4 md:flex-row">
            <section className="w-full rounded-2xl border border-slate-200 bg-white md:w-96 md:shrink-0">
              {tab === "identity" && list.length > 0 && (
                <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2 text-sm">
                  <label className="flex items-center gap-2">
                    <input type="checkbox" checked={picked.length === list.length}
                      onChange={(e) => setPicked(e.target.checked ? list.map((q) => q.qid) : [])} />전체
                  </label>
                  <button disabled={!picked.length}
                    onClick={async () => { await api.bulkAccept(picked); setMsg({ text: `${picked.length}건 일괄 승인했습니다.` }); refresh(); }}
                    className="rounded-lg bg-blue-600 px-3 py-1 text-white disabled:bg-slate-300">권장대로 일괄 승인</button>
                </div>
              )}
              {list.length === 0 && <div className="p-6 text-sm text-slate-500">이 탭에 남은 질문이 없습니다.</div>}
              <ul className="max-h-[60vh] overflow-y-auto">
                {list.map((q) => (
                  <li key={q.qid} className={`flex items-start gap-2 border-b border-slate-50 px-4 py-2.5 ${sel === q.qid ? "bg-blue-50" : ""}`}>
                    {tab === "identity" && (
                      <input type="checkbox" className="mt-1" checked={picked.includes(q.qid)}
                        onChange={(e) => setPicked(e.target.checked ? [...picked, q.qid] : picked.filter((x) => x !== q.qid))} />
                    )}
                    <button onClick={() => setSel(q.qid)} className="min-w-0 flex-1 text-left">
                      <div className="line-clamp-2 text-sm">{q.text}</div>
                      <div className="mt-1 flex gap-2 text-xs text-slate-400">
                        <span className="rounded bg-slate-100 px-1.5">{q.context?.source?.records ? "기록" : q.context?.source?.url ? "웹" : "LLM"}</span>
                        {q.count > 1 && <span>×{q.count}</span>}
                        <span>{new Date(q.created_at * 1000).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            <section className="min-w-0 flex-1">
              {detail ? <Detail q={detail} onAct={act} /> : (
                <div className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">질문을 고르세요.</div>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function Sources({ st, onChange, onRun }: { st: KgStatus | null; onChange: () => void; onRun: (run: string) => void }) {
  const file = useRef<HTMLInputElement>(null);
  const [pages, setPages] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function up() {
    const f = file.current?.files?.[0];
    if (!f) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.uploadManual(f, pages.trim() || undefined);
      if (file.current) file.current.value = "";
      onChange();
      onRun(r.run_id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-center gap-2">
        <FileUp size={18} className="text-slate-500" aria-hidden />
        <span className="font-semibold">매뉴얼 추가</span>
        <input ref={file} type="file" accept="application/pdf,.pdf" className="text-sm" />
        <input value={pages} onChange={(e) => setPages(e.target.value)} placeholder="쪽 범위 (예: 1-12, 비우면 전체)"
          className="w-44 rounded-lg border border-slate-200 px-2 py-1 text-sm" />
        <button onClick={up} disabled={busy} className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm text-white disabled:bg-slate-300">
          {busy ? "올리는 중…" : "올리고 구축"}
        </button>
        <button onClick={async () => { const r = await api.kgBuild(); onChange(); onRun(r.run_id); }}
          className="ml-auto flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm ring-1 ring-slate-200 hover:bg-slate-50">
          <RefreshCw size={14} aria-hidden className={st?.building ? "animate-spin" : ""} />
          {st?.building ? "구축 중…" : "구축 이어서 (기록 후보 포함)"}
        </button>
      </div>
      {err && <div className="mt-2 text-sm text-red-600">{err}</div>}
      {st && st.docs.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {st.docs.map((d) => (
            <li key={d.doc_id} className="flex items-center gap-3 text-sm">
              <span className="min-w-0 flex-1 truncate">{d.title} <span className="text-xs text-slate-400">{d.doc_id}</span></span>
              <div className="h-1.5 w-32 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full bg-blue-500" style={{ width: `${d.chunks ? (d.done / d.chunks) * 100 : 0}%` }} />
              </div>
              <span className="w-20 text-right text-xs tabular-nums text-slate-500">{d.done}/{d.chunks} 청크</span>
              <span className={`w-16 text-xs ${d.status === "error" ? "text-red-600" : d.status === "done" ? "text-emerald-600" : "text-blue-600"}`}>
                {DOC_STATUS[d.status] ?? d.status}
              </span>
              {(d.status === "paused" || d.status === "error") && (
                <button onClick={async () => { const r = await api.kgBuild(d.doc_id); onChange(); onRun(r.run_id); }}
                  className="text-xs text-blue-600 underline">이어서</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Detail({ q, onAct }: { q: Question; onAct: (action: string, reason?: string, edit?: Record<string, unknown>) => void }) {
  const nav = useNavigate();
  const [showRec, setShowRec] = useState(q.tab !== "held");
  const [rejecting, setRejecting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => { setShowRec(q.tab !== "held"); setRejecting(false); setEditing(false); setForm({}); }, [q.qid, q.tab]);
  const src = q.source;
  const claim = q.recommended?.claim;
  const needsReason = ["relation", "spec", "held", "conflict"].includes(q.kind);
  const set = (k: string) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const editPayload = (): Record<string, unknown> => {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(form)) if (v.trim()) out[k] = ["lo", "hi"].includes(k) ? Number(v) : v.trim();
    return out;
  };
  const btn = "rounded-lg px-3 py-1.5 text-sm";

  return (
    <div className="space-y-3">
      {src && src.kind !== "none" && (
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          {src.kind === "record" ? (
            <>
              <div className="text-xs font-semibold text-slate-500">실험 기록 {src.records?.length ?? 0}건</div>
              <div className="mt-2 flex flex-wrap gap-1">
                {src.records?.map((r) => (
                  <button key={r} onClick={() => nav(`/notes/${r}`)} className="rounded bg-slate-100 px-2 py-0.5 text-xs hover:bg-slate-200">{r}</button>
                ))}
              </div>
              {src.text && <div className="mt-2 text-xs text-slate-500">{src.text}</div>}
            </>
          ) : (
            <>
              <div className="text-xs font-semibold text-slate-500">
                {src.kind === "web" ? "웹 발췌" : "매뉴얼"} · {src.title}{src.page ? ` · ${src.page}쪽` : ""}
                {src.url && <a href={src.url} target="_blank" rel="noreferrer" className="ml-2 text-blue-600 underline">원문</a>}
              </div>
              <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-700">
                {highlight(src.text ?? "", src.quote ?? "").map((p, i) =>
                  p.mark ? <mark key={i} className="rounded bg-amber-200 px-0.5">{p.text}</mark> : <span key={i}>{p.text}</span>)}
              </p>
            </>
          )}
        </div>
      )}

      <div className="space-y-3 rounded-2xl border-2 border-blue-200 bg-white p-4">
        <div className="font-semibold">{q.text}</div>
        {q.count > 1 && <div className="text-xs text-slate-500">같은 질문이 {q.count}곳에서 나왔습니다.</div>}
        {!showRec ? (
          <button onClick={() => setShowRec(true)} className="text-sm text-blue-600 underline">제안 보기</button>
        ) : (
          <div className="rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
            <div className="text-xs text-slate-400">이 답이 만들 것</div>
            {preview(q)}
          </div>
        )}
        {q.context?.predicate && (
          <div className="text-xs text-slate-500">
            술어 정의: {q.context.predicate.phrase_ko?.replace("{s}", "주어").replace("{o}", "목적어")} ·
            주어 {q.context.predicate.subject_kinds?.map((k: string) => KIND_KO[k] ?? k).join("·")} →
            목적어 {q.context.predicate.object_kinds?.map((k: string) => KIND_KO[k] ?? k).join("·")}
            {q.kind === "spec" && " · 범위는 같은 차원 단위끼리만 비교합니다"}
          </div>
        )}
        {q.kind === "identity" && q.context?.candidates?.length > 0 && (
          <div className="text-xs text-slate-500">후보: {q.context.candidates.map((c: { id: string; label: string; score: number }) => `${c.label}(${c.score})`).join(", ")}</div>
        )}

        <div className="flex flex-wrap gap-2">
          <button onClick={() => onAct("accept")} className={`${btn} bg-blue-600 text-white hover:bg-blue-700`}>
            {q.kind === "new_term" ? "등록" : q.kind === "identity" ? "같음" : "권장대로"}
          </button>
          <button onClick={() => (needsReason ? setRejecting(!rejecting) : onAct("reject"))}
            className={`${btn} ring-1 ring-red-200 text-red-700 hover:bg-red-50`}>{q.kind === "identity" ? "다름" : "아니오"}</button>
          <button onClick={() => setEditing(!editing)} className={`${btn} ring-1 ring-slate-200 hover:bg-slate-50`}>수정</button>
          <button onClick={() => onAct("hold")} className={`${btn} ring-1 ring-slate-200 hover:bg-slate-50`}>보류</button>
          <button onClick={() => onAct("skip")} className={`${btn} text-slate-500 hover:bg-slate-100`}>건너뛰기</button>
        </div>
        {rejecting && (
          <div className="flex flex-wrap gap-1">
            {REASONS.map((r) => (
              <button key={r.code} onClick={() => onAct("reject", r.code)}
                className="rounded-full bg-red-50 px-3 py-1 text-xs text-red-700 hover:bg-red-100">{r.label}</button>
            ))}
          </div>
        )}
        {editing && (
          <div className="grid gap-2 rounded-lg bg-slate-50 p-3 text-sm md:grid-cols-2">
            {(q.kind === "relation" || q.kind === "held" || q.kind === "conflict") && claim && (
              <>
                <label className="flex flex-col gap-1">술어
                  <select defaultValue={claim.predicate} onChange={set("predicate")} className="rounded border border-slate-200 px-2 py-1">
                    {PREDICATES.map((p) => <option key={p}>{p}</option>)}
                  </select>
                </label>
                <label className="flex items-center gap-2">
                  <input type="checkbox" onChange={(e) => setForm({ ...form, swap: e.target.checked ? "1" : "" })} />방향 뒤집기
                </label>
                <label className="flex flex-col gap-1">주어 용어 id<input onChange={set("subject_id")} placeholder={claim.subject_id ?? claim.subject} className="rounded border border-slate-200 px-2 py-1" /></label>
                <label className="flex flex-col gap-1">목적어 용어 id<input onChange={set("object_id")} placeholder={claim.object_id ?? claim.object} className="rounded border border-slate-200 px-2 py-1" /></label>
              </>
            )}
            {q.kind === "spec" && (
              <>
                <label className="flex flex-col gap-1">최소<input type="number" onChange={set("lo")} className="rounded border border-slate-200 px-2 py-1" /></label>
                <label className="flex flex-col gap-1">최대<input type="number" onChange={set("hi")} className="rounded border border-slate-200 px-2 py-1" /></label>
                <label className="flex flex-col gap-1">단위<input onChange={set("unit")} placeholder="°C, s, min, mol%" className="rounded border border-slate-200 px-2 py-1" /></label>
                <label className="flex flex-col gap-1">구분
                  <select onChange={set("spec_kind")} defaultValue={claim?.spec_kind ?? "allowed"} className="rounded border border-slate-200 px-2 py-1">
                    <option value="allowed">허용</option><option value="recommended">권장</option>
                  </select>
                </label>
              </>
            )}
            {q.kind === "identity" && (
              <label className="flex flex-col gap-1 md:col-span-2">다른 용어 고르기
                <select onChange={set("term_id")} className="rounded border border-slate-200 px-2 py-1" defaultValue="">
                  <option value="" disabled>후보에서 고르세요</option>
                  {q.context?.candidates?.map((c: { id: string; label: string }) => <option key={c.id} value={c.id}>{c.label} ({c.id})</option>)}
                </select>
              </label>
            )}
            {q.kind === "new_term" && (
              <>
                <label className="flex flex-col gap-1">라벨(영문)<input onChange={set("label")} placeholder={q.recommended?.new_term?.label} className="rounded border border-slate-200 px-2 py-1" /></label>
                <label className="flex flex-col gap-1">표시 이름(한국어)<input onChange={set("label_ko")} placeholder={q.recommended?.new_term?.label_ko} className="rounded border border-slate-200 px-2 py-1" /></label>
                <label className="flex flex-col gap-1">종류
                  <select onChange={set("kind")} defaultValue={q.recommended?.new_term?.kind} className="rounded border border-slate-200 px-2 py-1">
                    {Object.entries(KIND_KO).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1">상위 개념 id<input onChange={set("parent")} placeholder={q.recommended?.new_term?.parent ?? "없음"} className="rounded border border-slate-200 px-2 py-1" /></label>
                <label className="flex flex-col gap-1 md:col-span-2">또는 기존 용어에 연결 (용어 id)
                  <input onChange={set("term_id")} placeholder="예: lg:precatalyst_g3" className="rounded border border-slate-200 px-2 py-1" />
                </label>
              </>
            )}
            <div className="md:col-span-2">
              <button onClick={() => onAct("edit", undefined, editPayload())} className={`${btn} bg-slate-800 text-white`}>수정해서 승인</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AutoList({ items, onRevoke }: { items: AutoItem[]; onRevoke: (id: string) => void }) {
  if (!items.length) return <div className="rounded-2xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-400">자동 승인된 관계가 없습니다.</div>;
  return (
    <ul className="space-y-2">
      {items.map((it) => (
        <li key={it.item_id} className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4 text-sm">
          <span className="rounded bg-emerald-100 px-2 py-0.5 text-xs text-emerald-700">코드 자동 승인</span>
          <span className="min-w-0 flex-1">
            {it.payload.subject} —{it.payload.predicate}→ {it.payload.object}
            <span className="block truncate text-xs text-slate-400">"{it.payload.quote}"</span>
          </span>
          <button onClick={() => onRevoke(it.item_id)} className="rounded-lg px-3 py-1 text-xs text-red-700 ring-1 ring-red-200 hover:bg-red-50">취소</button>
        </li>
      ))}
    </ul>
  );
}
