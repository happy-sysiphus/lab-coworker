import { useSearchParams } from "react-router-dom";
import ReplayView from "../components/ReplayView";
import RunsView from "../components/RunsView";
import { MobileBar } from "../nav";

// 워크플로 뷰 — "제품 실행"은 이 볼트의 실행 기록을, "실험 재생"은 하네스 본실험 v1을 재생한다.
// 전시 기본 화면은 실험 재생이고, ?run=<id>로 들어오면 제품 실행 탭에서 그 실행을 연다.
const TABS = [
  { key: "runs", label: "제품 실행" },
  { key: "replay", label: "실험 재생" },
] as const;

export default function Flow() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? (params.get("run") ? "runs" : "replay");
  return (
    <div className="flex h-screen flex-col">
      <MobileBar title="워크플로" subtitle="실행 재생" />
      <header className="hidden border-b border-slate-200 bg-white px-6 py-3 md:block">
        <div className="font-bold">워크플로</div>
        <div className="text-xs text-slate-400">LAB GENE이 실제로 어떻게 움직였는지 단계별로 재생합니다.</div>
      </header>
      <nav className="flex gap-1 border-b border-slate-200 bg-white px-4">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setParams({ tab: t.key })}
            className={`border-b-2 px-4 py-2.5 text-sm font-medium ${tab === t.key
              ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
            {t.label}
          </button>
        ))}
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50">
        {tab === "runs" ? <RunsView initialRun={params.get("run")} /> : <ReplayView />}
      </div>
    </div>
  );
}
