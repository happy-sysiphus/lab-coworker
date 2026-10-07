import { useEffect, useState } from "react";
import { Library, Send } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { MobileBar } from "../nav";
import { listSessions, newSession, saveSession } from "../store";

export default function Home() {
  const nav = useNavigate();
  const [mode, setMode] = useState<"log" | "ask">("log");
  const [text, setText] = useState("");
  const drafts = listSessions().filter((s) => s.kind !== "ask" && !s.saved && s.messages.length > 0);
  // 처음 쓰는 연구실이면 연구 도메인부터 고르게 안내한다
  const [noDomain, setNoDomain] = useState(false);
  useEffect(() => {
    api.config().then((c) => setNoDomain((c.domains ?? []).length === 0)).catch(() => setNoDomain(false));
  }, []);

  function start(kind: "log" | "ask", preset?: string) {
    const t = (preset ?? text).trim();
    if (!t) return;
    const s = newSession(kind);
    s.rawText = t;
    s.title = t.slice(0, 30);
    saveSession(s);
    nav(kind === "log" ? `/log/${s.id}` : `/ask/${s.id}`);
  }

  return (
    <>
    <MobileBar title="AI 워크스페이스" />
    <div className="mx-auto max-w-3xl px-5 py-10 md:px-8 md:py-16">
      {noDomain && (
        <button onClick={() => nav("/domains")}
          className="mb-6 flex w-full items-center gap-3 rounded-2xl border border-blue-200 bg-blue-50 p-4 text-left hover:bg-blue-100">
          <Library className="shrink-0 text-blue-600" size={22} aria-hidden />
          <span>
            <span className="block font-semibold text-blue-900">먼저 연구 도메인을 고르세요</span>
            <span className="block text-sm text-blue-800">도메인에 맞는 오픈소스 온톨로지가 기록과 질의의 어휘가 됩니다.</span>
          </span>
        </button>
      )}
      <h1 className="text-2xl font-bold md:text-3xl">무엇을 도와드릴까요?</h1>
      <p className="mt-2 text-sm text-slate-500 md:text-base">실험 기록, 문제 원인, 과거 사례를 자연어로 입력하면 AI가 정리합니다.</p>

      <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-3 flex gap-1 rounded-lg bg-slate-100 p-1 text-sm w-fit">
          {(["log", "ask"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              className={`rounded-md px-4 py-1.5 ${mode === m ? "bg-white font-medium shadow" : "text-slate-500"}`}>
              {m === "log" ? "실험 기록" : "문제 질문"}
            </button>
          ))}
        </div>
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4}
          placeholder={mode === "log" ? "실험 내용을 자유롭게 입력하세요." : "문제 상황을 설명해주세요. 장비·재료·증상을 포함하면 더 정확합니다."}
          className="w-full resize-none outline-none placeholder:text-slate-400" />
        <div className="flex justify-end">
          <button onClick={() => start(mode)} disabled={!text.trim()}
            className="rounded-full bg-blue-600 px-5 py-2 text-sm text-white disabled:opacity-40">
            <span className="inline-flex items-center gap-2">전송 <Send size={16} strokeWidth={2} aria-hidden="true" /></span>
          </button>
        </div>
      </div>

      {drafts.length > 0 && (
        <div className="mt-10 rounded-xl border border-amber-200 bg-amber-50 p-4">
          <div className="font-medium">최근 미완료 기록 {drafts.length}건</div>
          <div className="text-sm text-slate-500">누락 정보를 이어서 입력하고 저장할 수 있어요.</div>
          <div className="mt-3 space-y-2">
            {drafts.map((d) => (
              <div key={d.id} className="flex items-center justify-between rounded-lg bg-white px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{d.title}</div>
                  <div className="text-xs text-slate-400">
                    {new Date(d.createdAt).toLocaleString("ko-KR")}
                    {d.kind === "followup" && " · 후속 실험"}
                  </div>
                </div>
                <button onClick={() => nav(d.kind === "followup" ? `/followup/${d.id}` : `/log/${d.id}`)}
                  className="shrink-0 rounded-full border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50">
                  이어 작성
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
    </>
  );
}
