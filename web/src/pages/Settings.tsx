import { useState } from "react";
import DomainPicker from "../components/DomainPicker";
import { api } from "../api";
import { useAuth } from "../auth";
import { MobileBar } from "../nav";

export default function Settings() {
  const { me, refreshLab } = useAuth();
  const lab = me?.lab;
  const [name, setName] = useState(lab?.name ?? "");
  const [mode, setMode] = useState<"central" | "own">(lab?.llm_mode ?? "central");
  const [provider, setProvider] = useState(lab?.llm_provider ?? "claude");
  const [credential, setCredential] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function act(patch: Parameters<typeof api.labSettings>[0], done: string) {
    setBusy(true); setMsg(null);
    try { await api.labSettings(patch); await refreshLab(); setCredential(""); setMsg(done); }
    catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  }

  if (!lab || me?.role !== "admin")
    return <div className="p-8 text-slate-500">관리자만 접근할 수 있습니다.</div>;

  // own으로 처음 전환할 땐 크레덴셜이 없으면 서버가 502를 내므로 저장을 막는다.
  // 단 codex·gemini는 서버 머신의 CLI 로그인을 쓸 수 있어 키가 선택이다.
  const keyOptional = provider === "codex" || provider === "gemini";
  const modeChangedToOwn = mode === "own" && lab.llm_mode !== "own";
  const canSave = !busy && !(modeChangedToOwn && !credential.trim() && !keyOptional);
  const used = me.usage_today;
  const pct = Math.min(100, Math.round((used / Math.max(1, lab.daily_llm_limit)) * 100));

  function save() {
    const patch: Parameters<typeof api.labSettings>[0] = {};
    if (name.trim() && name.trim() !== lab!.name) patch.name = name.trim();
    if (mode !== lab!.llm_mode) patch.llm_mode = mode;
    if (mode === "own") {
      if (credential.trim()) {
        patch.llm_provider = provider;
        patch.llm_credential = credential.trim();
      } else if (provider !== (lab!.llm_provider ?? "")) {
        patch.llm_provider = provider;   // 키 없는 교체 — 서버가 이전 크레덴셜을 비운다
      }
    }
    void act(patch, "저장했습니다");
  }

  return (
    <>
      <MobileBar title="연구실 설정" />
      <div className="mx-auto max-w-2xl space-y-4 px-5 py-6 md:px-8 md:py-8">
        <h1 className="text-xl font-bold md:text-2xl">연구실 설정</h1>
        <section className="rounded-2xl border border-slate-200 bg-white p-5">
          <h2 className="mb-3 font-semibold">연구 도메인</h2>
          <DomainPicker />
        </section>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="text-xs text-slate-400">연구실 이름</div>
          <input value={name} onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-3 py-2 text-sm" />
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="flex items-baseline justify-between">
            <div className="font-semibold">오늘 사용량</div>
            <div className="text-sm text-slate-500">{used} / {lab.daily_llm_limit}</div>
          </div>
          <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div className={`h-full ${pct >= 90 ? "bg-red-500" : "bg-blue-600"}`}
              style={{ width: `${pct}%` }} />
          </div>
          <p className="mt-2 text-xs text-slate-400">
            일일 상한은 서비스 운영자가 연구실별로 정합니다. 조정이 필요하면 운영자에게 요청하세요.
          </p>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="font-semibold">초대 코드</div>
          <p className="mt-1 text-xs text-slate-500">이 코드로 연구실원이 합류합니다.</p>
          <div className="mt-2 flex items-center gap-3">
            <code className="rounded bg-slate-100 px-3 py-1.5 text-sm">{lab.invite_code}</code>
            <button onClick={() => void act({ rotate_invite: true }, "재발급했습니다")} disabled={busy}
              className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-40">
              재발급
            </button>
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="font-semibold">멤버</div>
          <div className="mt-2 space-y-1 text-sm">
            {(me.members ?? []).map((m) => (
              <div key={m.user_id} className="flex justify-between gap-3">
                <span className="truncate">{m.email}</span>
                <span className="shrink-0 text-slate-400">{m.role === "admin" ? "관리자" : "멤버"}</span>
              </div>
            ))}
            {!me.members?.length && <div className="text-slate-400">—</div>}
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-5">
          <div className="font-semibold">LLM 모드</div>
          <div className="mt-2 flex gap-2">
            {(["central", "own"] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={`rounded-full border px-4 py-1.5 text-sm ${mode === m
                  ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-300"}`}>
                {m === "central" ? "중앙 (기본)" : "연구실 크레덴셜"}
              </button>
            ))}
          </div>
          {mode === "own" && (
            <div className="mt-3 space-y-2">
              <select value={provider} onChange={(e) => setProvider(e.target.value)}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm">
                <option value="claude">Claude CLI — 장기 토큰 (claude setup-token)</option>
                <option value="api">Anthropic API 키 (CLI 없이 직접 호출)</option>
                <option value="codex">Codex CLI — OpenAI 키 또는 서버 로그인</option>
                <option value="gemini">Gemini CLI — API 키 또는 서버 로그인</option>
              </select>
              <input type="password" value={credential} onChange={(e) => setCredential(e.target.value)}
                placeholder={keyOptional
                  ? "API 키 (비우면 서버의 CLI 로그인 사용)"
                  : lab.llm_mode === "own" ? "등록됨 — 교체하려면 새 값 입력" : "토큰/키 입력"}
                className="w-full rounded border border-slate-300 px-3 py-2 text-sm" />
              <p className="text-xs text-slate-400">저장 후 값은 다시 표시되지 않습니다.</p>
            </div>
          )}
        </div>

        {msg && <div className="text-sm text-slate-600">{msg}</div>}
        <button onClick={save} disabled={!canSave}
          className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white disabled:opacity-40 md:w-auto md:px-8">
          저장
        </button>
      </div>
    </>
  );
}
