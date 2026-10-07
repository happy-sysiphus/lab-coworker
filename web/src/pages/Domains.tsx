import DomainPicker from "../components/DomainPicker";
import { useAuth } from "../auth";
import { MobileBar } from "../nav";

export default function Domains() {
  const { mode, me } = useAuth();
  return (
    <div className="flex h-screen flex-col">
      <MobileBar title="연구 도메인" subtitle="온톨로지 선택" />
      <header className="hidden border-b border-slate-200 bg-white px-6 py-3 md:block">
        <div className="font-bold">연구 도메인</div>
        <div className="text-xs text-slate-400">
          연구실의 도메인을 고르면 그 분야의 오픈소스 온톨로지 조합이 기록과 질의의 어휘가 됩니다.
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50 p-4 md:p-6">
        <DomainPicker readOnly={mode === "deploy" && me?.role !== "admin"} />
      </div>
    </div>
  );
}
