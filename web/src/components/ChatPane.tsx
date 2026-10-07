import { useEffect, useRef, useState } from "react";
import { GitFork, Send, Undo2 } from "lucide-react";
import type { ChatMsg } from "../types";

export default function ChatPane({ messages, onSend, busy, busyText, placeholder, onRewind, onFork }: {
  messages: ChatMsg[];
  onSend: (text: string) => void;
  busy: boolean;
  busyText?: string;   // 대기 중 문구 — Ask는 실행 기록의 마지막 단계를 띄운다
  placeholder?: string;
  onRewind?: (uIdx: number) => void; // uIdx = 사용자 발화 순번 (0=초기 로그)
  onFork?: (uIdx: number) => void;
}) {
  const [text, setText] = useState("");
  const bottom = useRef<HTMLDivElement>(null);
  // 블록 본문 필수 — 간결 본문이면 scrollIntoView의 반환값이 그대로 effect 반환값이 되고,
  // React가 그것을 정리 함수로 보고 호출한다. 확장/폴리필이 이 API를 덮어써 값을 돌려주면
  // 다음 렌더나 언마운트에서 "is not a function"으로 트리 전체가 죽는다.
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ behavior: "smooth" });
  }, [messages, busy]);

  function send(t: string) {
    if (!t.trim() || busy) return;
    setText("");
    onSend(t.trim());
  }

  // 사용자 발화 순번 부여 — 되감기·포크가 스냅샷 인덱스로 역산할 키
  let u = -1;
  const rows = messages.map((m, i) => {
    if (m.role === "user") u += 1;
    return { m, i, uIdx: m.role === "user" ? u : -1 };
  });

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 md:p-6">
        {rows.map(({ m, i, uIdx }) => (
          <div key={i} className="group">
            <div className={`text-xs text-slate-400 ${m.role === "user" ? "text-right" : ""}`}>
              {m.role === "user" ? "사용자" : "LAB GENE AI"}
            </div>
            <div className={m.role === "user"
              ? "ml-auto w-fit max-w-[80%] rounded-xl bg-blue-50 px-4 py-3 text-sm whitespace-pre-wrap"
              : "w-fit max-w-[85%] rounded-xl border-l-4 border-blue-500 bg-white px-4 py-3 text-sm shadow-sm whitespace-pre-wrap"}>
              {m.text}
            </div>
            {m.role === "user" && uIdx >= 1 && !busy && (onRewind || onFork) && (
              <div className="mt-1 flex justify-end gap-1">
                {onRewind && (
                  <button onClick={() => onRewind(uIdx)} aria-label="이 답변 전으로 되감기"
                    title="이 답변 전으로 되감기"
                    className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-blue-600"><Undo2 aria-hidden strokeWidth={2} size={16} /></button>
                )}
                {onFork && (
                  <button onClick={() => onFork(uIdx)} aria-label="여기서 새 대화로 포크"
                    title="여기서 새 대화로 포크"
                    className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-blue-600"><GitFork aria-hidden strokeWidth={2} size={16} /></button>
                )}
              </div>
            )}
            {m.role === "ai" && m.chips && i === messages.length - 1 && !busy && (
              <div className="mt-2 flex flex-wrap gap-2">
                {m.chips.map((c) => (
                  <button key={c} onClick={() => send(c)}
                    className="rounded-full border border-slate-300 bg-white px-3 py-1 text-sm hover:border-blue-400 hover:text-blue-600">
                    {c}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {busy && <div className="text-sm text-slate-400 animate-pulse">{busyText ?? "분석 중... (수십 초 걸릴 수 있어요)"}</div>}
        <div ref={bottom} />
      </div>
      <div className="shrink-0 border-t border-slate-200 bg-white p-3 md:p-4">
        <div className="flex items-center gap-2 rounded-full border border-slate-300 px-4 py-2">
          <input value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.nativeEvent.isComposing && send(text)}
            placeholder={placeholder ?? "메시지를 입력하세요"} disabled={busy}
            className="flex-1 text-sm outline-none disabled:bg-transparent" />
          <button onClick={() => send(text)} disabled={busy || !text.trim()} aria-label="메시지 전송"
            className="grid size-10 shrink-0 place-items-center rounded-full bg-blue-600 text-white disabled:opacity-40"><Send aria-hidden strokeWidth={2} size={16} /></button>
        </div>
      </div>
    </div>
  );
}
