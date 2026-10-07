import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Domain, DomainsInfo } from "../types";

// 연구 도메인 고르기 — 모든 도메인을 고를 수 있고, 실제로 적재되는 어휘는 실험한 재료·공정·화학 온톨로지 하나다.
const KIND_KO: Record<string, string> = {
  material: "물질", technique: "기법", parameter: "파라미터", metric: "지표", cause: "원인", equipment: "장비",
};

export default function DomainPicker({ readOnly = false }: { readOnly?: boolean }) {
  const nav = useNavigate();
  const [info, setInfo] = useState<DomainsInfo | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ notice: string | null; run_id: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.domains()
      .then((d) => { setInfo(d); setPicked(d.selected); setOpen(d.active); })
      .catch((e) => setError((e as Error).message));
  }, []);

  if (error) return <div className="text-sm text-red-600">도메인 목록을 불러오지 못했습니다 — {error}</div>;
  if (!info) return <div className="text-sm text-slate-500">불러오는 중…</div>;

  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const showcase = picked.some((id) => id !== info.active) || (picked.length > 0 && !picked.includes(info.active));
  const dirty = picked.join(",") !== info.selected.join(",");

  async function save() {
    setBusy(true); setError(null);
    try {
      const out = await api.setDomains(picked);
      setInfo({ ...info!, selected: out.domains });
      setMsg(out);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        {info.domains.map((d) => (
          <DomainCard key={d.id} d={d} info={info} checked={picked.includes(d.id)} expanded={open === d.id}
            onToggle={() => !readOnly && toggle(d.id)} onExpand={() => setOpen(open === d.id ? null : d.id)} />
        ))}
      </div>
      {showcase && (
        <div className="rounded-lg bg-amber-50 px-4 py-2 text-sm text-amber-800">
          시연에서는 실험한 재료·공정·화학 온톨로지로 진행합니다.
        </div>
      )}
      {!readOnly && (
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={save} disabled={busy || picked.length === 0 || !dirty}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700 disabled:bg-slate-300">
            {busy ? "저장 중…" : "선택 저장"}
          </button>
          {picked.length === 0 && <span className="text-xs text-slate-500">도메인을 하나 이상 고르세요.</span>}
          {msg && (
            <span className="text-sm text-slate-600">
              저장했습니다.{" "}
              <button onClick={() => nav(`/flow?run=${msg.run_id}`)} className="text-blue-600 underline-offset-2 hover:underline">
                워크플로에서 보기
              </button>
            </span>
          )}
        </div>
      )}
      {readOnly && <div className="text-xs text-slate-500">연구 도메인은 관리자만 바꿀 수 있습니다.</div>}
    </div>
  );
}

function DomainCard({ d, info, checked, expanded, onToggle, onExpand }: {
  d: Domain; info: DomainsInfo; checked: boolean; expanded: boolean; onToggle: () => void; onExpand: () => void;
}) {
  const active = d.id === info.active;
  return (
    <div className={`rounded-2xl border-2 bg-white p-4 ${checked ? "border-blue-500" : "border-slate-200"}`}>
      <div className="flex items-start gap-3">
        <button onClick={onToggle} aria-pressed={checked} aria-label={`${d.name} 선택`}
          className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded border ${checked ? "border-blue-600 bg-blue-600 text-white" : "border-slate-300"}`}>
          {checked && <Check size={14} aria-hidden />}
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">{d.name}</span>
            <span className={`rounded-full px-2 py-0.5 text-xs ${active ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
              {active ? "실제 진행" : "준비 중"}
            </span>
          </div>
          {d.description && <div className="mt-1 text-xs text-slate-500">{d.description}</div>}
          <div className="mt-1 text-xs text-slate-400">{d.bundle.map((b) => b.ontology).join(" · ")}</div>
        </div>
        <button onClick={onExpand} aria-label="번들 보기" className="text-slate-400 hover:text-slate-700">
          {expanded ? <ChevronDown size={18} aria-hidden /> : <ChevronRight size={18} aria-hidden />}
        </button>
      </div>
      {expanded && (
        <div className="mt-3 space-y-3">
          {active && (
            <div className="rounded-lg bg-emerald-50 p-3 text-xs text-emerald-800">
              실제 적재 어휘 <b>{info.vocabulary}</b> · 용어 {info.vocab.terms}개, 단위 {info.vocab.units}개, 술어 {info.vocab.predicates}개
              <div className="mt-1 flex flex-wrap gap-1">
                {Object.entries(info.vocab.by_kind).map(([k, n]) => (
                  <span key={k} className="rounded bg-white px-1.5 py-0.5">{KIND_KO[k] ?? k} {n}</span>
                ))}
              </div>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-left text-slate-400">
                <tr><th className="py-1 pr-2 font-normal">온톨로지</th><th className="pr-2 font-normal">맡는 영역</th>
                  <th className="pr-2 font-normal">버전</th><th className="pr-2 font-normal">라이선스</th><th className="font-normal">규모</th></tr>
              </thead>
              <tbody>
                {d.bundle.map((b) => {
                  const m = info.ontologies[b.ontology];
                  return (
                    <tr key={b.ontology} className="border-t border-slate-100 align-top">
                      <td className="py-1 pr-2 font-medium">
                        {m?.url ? <a href={m.url} target="_blank" rel="noreferrer" className="text-blue-700 hover:underline">{b.ontology}</a> : b.ontology}
                      </td>
                      <td className="pr-2 text-slate-600">{b.role}</td>
                      <td className="pr-2 text-slate-500">{m?.version ?? "—"}</td>
                      <td className="pr-2 text-slate-500">{m?.license ?? "—"}</td>
                      <td className="text-slate-500">{m?.size ?? "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
