import { useEffect, useRef, useState } from "react";
import { CircleCheck, Info, TriangleAlert } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { bannerKey, CARD_KIND_LABEL, cardLink, modeNote } from "../ask";
import { stageLabel } from "../flow";
import ChatPane from "../components/ChatPane";
import RecordCard from "../components/RecordCard";
import { MobileBar, MobileTabs } from "../nav";
import { getSession, saveSession } from "../store";
import type { EvidenceCard, Session } from "../types";

// 근거 라벨 — 사례 / 지식만 / 웹 / 근거 없음. 답변의 출처를 정직하게 밝힌다
const BANNERS = {
  none: { text: "연구실 기록·지식에 근거가 없어 일반 지식 기반 조언입니다.", Icon: TriangleAlert, cls: "bg-red-50 text-red-700" },
  knowledge: { text: "직접 유사한 실험 기록은 없어 연구실 지식(위키·승인 관계) 기반 안내입니다.", Icon: Info, cls: "bg-blue-50 text-blue-700" },
  web: { text: "연구실 기록과 지식에 없는 질문이라 웹 근거로 답했습니다. 연구실 검증 전 정보입니다.", Icon: Info, cls: "bg-amber-50 text-amber-700" },
  records: { text: "연구실 실험 기록을 근거로 한 답변입니다.", Icon: CircleCheck, cls: "bg-emerald-50 text-emerald-700" },
} as const;

export default function Ask() {
  const { sid } = useParams();
  const nav = useNavigate();
  const [session, setSession] = useState<Session | null>(() => getSession(sid ?? "") ?? null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"chat" | "panel">("chat");
  const started = useRef(false);

  function update(s: Session) {
    saveSession(s);
    setSession({ ...s });
  }

  async function runAsk(s: Session, text: string) {
    setBusy(true);
    setError(null);
    setStage(null);
    // 실행 id를 먼저 만들어 보내고, 기다리는 동안 실행 기록의 마지막 단계를 띄운다
    const runId = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
    let done = false;
    let last = 0;
    void (async () => {
      while (!done) {
        await new Promise((r) => setTimeout(r, 1500));
        if (done) break;
        try {
          const r = await api.flowRun(runId, last);
          const e = r.events[r.events.length - 1];
          if (e && !done) { last = e.seq; setStage(`${stageLabel(e.stage)} · ${e.summary}`); }
        } catch { /* 아직 시작 전인 실행 */ }
      }
    })();
    try {
      const result = await api.ask(text, runId);
      s.askResult = result;
      s.title = text.slice(0, 30);
      s.messages.push({ role: "ai", text: result.answer });
      update(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      done = true;
      setBusy(false);
      setStage(null);
    }
  }

  useEffect(() => {
    if (!session || started.current) return;
    started.current = true;
    if (session.rawText && session.messages.length === 0) {
      session.messages.push({ role: "user", text: session.rawText });
      void runAsk(session, session.rawText);
    }
  }, [session]);

  if (!session) return <div className="p-8 text-slate-500">세션을 찾을 수 없습니다.</div>;
  const result = session.askResult;
  const banner = result ? BANNERS[bannerKey(result.evidence)] : null;
  const note = result ? modeNote(result) : null;
  const cards = (result?.cards ?? []).filter((c) => c.kind !== "rec" && c.kind !== "web");   // 사례는 위 목록에 이미 있다
  const webCards = (result?.cards ?? []).filter((c) => c.kind === "web");

  return (
    <div className="flex h-screen flex-col md:flex-row">
      {/* 모바일에서 '유사 사례' 탭이면 이 열은 바·탭만 차지하고 남는 높이를 패널에 넘긴다 */}
      <div className={`flex min-w-0 flex-col md:min-h-0 md:flex-1 ${tab === "chat" ? "min-h-0 flex-1" : "shrink-0"}`}>
        <MobileBar title={session.title === "새 대화" ? "과거 기록 분석" : session.title} subtitle="과거 기록 분석" />
        <header className="hidden border-b border-slate-200 bg-white px-6 py-3 md:block">
          <div className="font-bold">{session.title === "새 대화" ? "과거 기록 분석" : session.title}</div>
          <div className="text-xs text-slate-400">과거 기록 분석</div>
        </header>
        <MobileTabs value={tab} onChange={setTab} tabs={[
          { key: "chat", label: "대화" },
          { key: "panel", label: <>유사 사례{session.askResult ? ` · ${session.askResult.records.length}` : ""}</> },
        ]} />
        {banner && (
          <div className={`flex items-center gap-2 px-6 py-2 text-sm ${banner.cls}`}>
            <banner.Icon size={16} strokeWidth={2} aria-hidden="true" />
            {banner.text}
          </div>
        )}
        {note && <div className="px-6 py-1 text-xs text-slate-500">{note}</div>}
        {result?.warnings && result.warnings.length > 0 && (
          <div className="px-6 py-1 text-xs text-amber-700">검증 경고: {result.warnings.join(" · ")}</div>
        )}
        {error && (
          <div className="flex flex-wrap gap-3 bg-red-50 px-6 py-2 text-sm text-red-700">
            {error}
            <button onClick={() => runAsk(session, session.rawText)} className="underline">재시도</button>
          </div>
        )}
        <div className={`min-h-0 flex-1 ${tab === "chat" ? "" : "hidden md:block"}`}>
          <ChatPane messages={session.messages} busy={busy} busyText={stage ? `${stage} …` : undefined}
            placeholder="추가 질문을 입력하세요"
            onSend={(t) => {
              session.messages.push({ role: "user", text: t });
              session.rawText = t;
              update(session);
              void runAsk(session, t);
            }} />
        </div>
      </div>
      <div className={`min-h-0 w-full flex-1 overflow-y-auto border-slate-200 bg-white p-5
        md:w-80 md:flex-none md:shrink-0 md:border-l ${tab === "panel" ? "block" : "hidden md:block"}`}>
        <div className="text-lg font-bold">유사 사례</div>
        {!session.askResult && <div className="mt-4 text-sm text-slate-400">질문하면 관련 기록이 표시됩니다.</div>}
        <div className="mt-3 space-y-3">
          {session.askResult?.records.map((r) => (
            <RecordCard key={r.id} meta={r} onClick={() => nav(`/notes/${r.id}`)} />
          ))}
          {session.askResult && session.askResult.records.length === 0 && (
            <div className="text-sm text-slate-400">관련 레코드 없음</div>
          )}
        </div>
        {result?.run_id && (
          <button onClick={() => nav(`/flow?run=${result.run_id}`)}
            className="mt-4 text-sm text-blue-600 underline-offset-2 hover:underline">
            이 답이 만들어진 과정 보기
          </button>
        )}
        {cards.length > 0 && (
          <div className="mt-5">
            <div className="text-xs text-slate-400">근거 카드</div>
            <div className="mt-2 space-y-2">
              {cards.map((c) => {
                const href = cardLink(c);
                return (
                  <button key={c.id} disabled={!href} onClick={() => href && nav(href)}
                    className="block w-full rounded-lg bg-slate-50 px-3 py-2 text-left text-sm enabled:hover:bg-slate-100">
                    <span className="mr-2 rounded bg-white px-1.5 py-0.5 text-xs text-slate-500">
                      {CARD_KIND_LABEL[c.kind] ?? c.kind}
                    </span>
                    <span className="font-medium">{c.title}</span>
                    <div className="mt-1 line-clamp-3 whitespace-pre-line text-xs text-slate-500">{c.text}</div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {webCards.length > 0 && (
          <div className="mt-5">
            <div className="text-xs text-slate-400">웹 근거 · 연구실 검증 전</div>
            <div className="mt-2 space-y-2">
              {webCards.map((c) => <WebCard key={`${result?.run_id}-${c.id}`} c={c} />)}
            </div>
          </div>
        )}
        {result && !result.cards && result.wiki.length > 0 && (
          <div className="mt-5">
            <div className="text-xs text-slate-400">참고한 위키</div>
            {result.wiki.map((w) => (
              <div key={w} className="mt-1 rounded bg-slate-50 px-2 py-1 text-sm">{w}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// 웹 카드 — 출처 링크, 원문 확인 표시, 지식 후보로 보내기(승인 화면에서 사람이 승인해야 그래프에 들어간다)
function WebCard({ c }: { c: EvidenceCard }) {
  const nav = useNavigate();
  const [state, setState] = useState<{ status: "idle" | "sending" | "sent" | "error"; runId?: string; msg?: string }>(
    { status: "idle" });
  const s = c.source;
  async function send() {
    setState({ status: "sending" });
    try {
      const r = await api.webSource(s.url ?? "", s.title ?? "", s.quote ?? "");
      setState({ status: "sent", runId: r.run_id });
    } catch (e) {
      setState({ status: "error", msg: e instanceof Error ? e.message : String(e) });
    }
  }
  return (
    <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm">
      <div className="flex items-center gap-2 text-xs">
        <span className="rounded bg-white px-1.5 py-0.5 text-slate-500">{c.id}</span>
        <span className={`rounded px-1.5 py-0.5 ${s.verified ? "bg-emerald-100 text-emerald-700" : "bg-slate-200 text-slate-600"}`}>
          {s.verified ? "원문 확인" : "확인 불가"}
        </span>
      </div>
      <a href={s.url} target="_blank" rel="noopener noreferrer"
        className="mt-1 block break-all font-medium text-blue-700 hover:underline">{s.title || s.url}</a>
      {s.quote && <blockquote className="mt-1 border-l-2 border-amber-300 pl-2 text-xs text-slate-600">{s.quote}</blockquote>}
      {s.summary && <div className="mt-1 text-xs text-slate-500">{s.summary}</div>}
      {state.status === "sent" ? (
        <div className="mt-2 flex flex-wrap gap-3 text-xs">
          <span className="text-emerald-700">지식 후보로 보냈습니다</span>
          <button onClick={() => nav("/review")} className="text-blue-600 hover:underline">검토 화면</button>
          {state.runId && (
            <button onClick={() => nav(`/flow?run=${state.runId}`)} className="text-blue-600 hover:underline">과정 보기</button>
          )}
        </div>
      ) : (
        <button onClick={send} disabled={state.status === "sending"}
          className="mt-2 rounded bg-white px-2 py-1 text-xs font-medium text-amber-800 ring-1 ring-amber-200 enabled:hover:bg-amber-100 disabled:opacity-60">
          {state.status === "sending" ? "보내는 중…" : "지식 후보로 보내기"}
        </button>
      )}
      {state.status === "error" && <div className="mt-1 text-xs text-red-600">{state.msg}</div>}
    </div>
  );
}
