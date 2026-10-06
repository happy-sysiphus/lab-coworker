import { useEffect, useMemo, useRef, useState } from "react";
import { X } from "lucide-react";
import { useNavigate } from "react-router-dom";
import ForceGraph2D from "react-force-graph-2d";
import { api } from "../api";
import { DEFAULT_HIDDEN, KIND_CHIP, KIND_COLOR, KIND_LABEL, toForceData } from "../graph";
import RecordCard from "../components/RecordCard";
import { MobileBar } from "../nav";
import type { KgGraph, KgNode, KgNodeKind, RecordMeta } from "../types";

export default function Graph() {
  const nav = useNavigate();
  const [graph, setGraph] = useState<KgGraph>({ nodes: [], links: [] });
  const [records, setRecords] = useState<RecordMeta[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hidden, setHidden] = useState<ReadonlySet<KgNodeKind>>(new Set(DEFAULT_HIDDEN));
  const [selected, setSelected] = useState<KgNode | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 600, h: 400 });

  // 그래프 구조는 서버(kg.sqlite), 상세 패널의 기록 카드는 레코드 목록에서 가져온다
  useEffect(() => {
    Promise.all([api.kgGraph(), api.listRecords()])
      .then(([g, r]) => { setGraph(g); setRecords(r.records); })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoaded(true));
  }, []);

  // 캔버스는 컨테이너를 자동 추적하지 않는다 — 마운트 때 즉시 재고,
  // 이후 패널 열림/창 크기 변화는 ResizeObserver로 따라간다.
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const update = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const data = useMemo(() => toForceData(graph, hidden), [graph, hidden]);

  // mutate 후 링크의 source/target은 노드 객체 — id로 되돌려 읽는다.
  const endId = (v: unknown): string =>
    typeof v === "object" && v !== null ? (v as { id: string }).id : (v as string);
  // 터치엔 호버가 없어 탭(선택)도 하이라이트 기준으로 삼는다
  const focus = hover ?? selected?.id ?? null;
  const linkTouchesFocus = (l: { source: unknown; target: unknown }) =>
    focus !== null && (endId(l.source) === focus || endId(l.target) === focus);

  const toggle = (k: KgNodeKind) => {
    const next = new Set(hidden);
    if (next.has(k)) next.delete(k); else next.add(k);
    setHidden(next);
    setSelected(null);
  };

  const related = selected ? records.filter((r) => selected.rec_ids.includes(r.id)) : [];
  const selectedRec = selected?.kind === "experiment"
    ? records.find((r) => r.id === selected.rec_ids[0]) : undefined;

  return (
    <div className="flex h-screen">
      <div className="flex min-w-0 flex-1 flex-col">
        <MobileBar title="그래프뷰" subtitle="관계 탐색" />
        <header className="hidden border-b border-slate-200 bg-white px-6 py-3 md:block">
          <div className="font-bold">그래프뷰</div>
          <div className="text-xs text-slate-400">
            실험·장비·재료·기법·지표·원인의 관계입니다. 점선 노드는 아직 어휘에 연결되지 않은 기록 표기입니다.
          </div>
        </header>
        <div ref={wrap} className="relative min-h-0 flex-1 bg-slate-50">
          <div className="absolute left-4 top-4 z-10 flex flex-wrap gap-2">
            {(Object.keys(KIND_LABEL) as KgNodeKind[]).map((k) => (
              <button key={k} onClick={() => toggle(k)}
                className={`rounded-full px-3 py-1 text-xs font-medium ${hidden.has(k) ? "bg-slate-100 text-slate-400 line-through" : KIND_CHIP[k]}`}>
                {KIND_LABEL[k]}
              </button>
            ))}
          </div>
          {error && <div className="p-8 text-sm text-red-600">그래프를 불러오지 못했습니다 — {error}</div>}
          {!error && loaded && graph.nodes.length === 0 && (
            <div className="p-8 text-sm text-slate-500">저장된 기록이 없습니다. 실험을 기록하면 그래프가 만들어져요.</div>
          )}
          {!error && graph.nodes.length > 0 && (
            <ForceGraph2D
              width={size.w} height={size.h}
              graphData={data}
              nodeCanvasObject={(node, ctx, scale) => {
                const n = node as unknown as KgNode & { x: number; y: number };
                const active = !focus || n.id === focus || !!data.adj.get(focus)?.has(n.id);
                ctx.globalAlpha = active ? 1 : 0.12;
                const r = n.kind === "experiment" ? 6 : 4;
                ctx.beginPath();
                ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
                if (n.status === "temp") {
                  ctx.setLineDash([2 / scale, 2 / scale]);
                  ctx.strokeStyle = KIND_COLOR[n.kind];
                  ctx.lineWidth = 1.5 / scale;
                  ctx.stroke();
                  ctx.setLineDash([]);
                } else {
                  ctx.fillStyle = KIND_COLOR[n.kind];
                  ctx.fill();
                }
                if (selected?.id === n.id || hover === n.id) {
                  ctx.strokeStyle = "#1e293b";
                  ctx.lineWidth = 1.5 / scale;
                  ctx.stroke();
                }
                ctx.font = `${11 / scale}px sans-serif`;
                ctx.textAlign = "center";
                ctx.textBaseline = "top";
                ctx.fillStyle = "#475569";
                ctx.fillText(n.label_ko || n.label, n.x, n.y + r + 2 / scale);
                ctx.globalAlpha = 1;
              }}
              nodePointerAreaPaint={(node, color, ctx) => {
                const n = node as unknown as { x: number; y: number };
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(n.x, n.y, 8, 0, 2 * Math.PI);
                ctx.fill();
              }}
              nodeLabel={(node) => {
                const n = node as unknown as KgNode;
                // 툴팁은 innerHTML로 들어간다 — 자유 서술(원인 등) 이스케이프 필수
                const esc = (s: string) =>
                  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                return esc(n.label_ko ? `${n.label_ko} (${n.label})` : n.full);
              }}
              linkColor={(l) => {
                if (!focus) return "#cbd5e1";
                return linkTouchesFocus(l as { source: unknown; target: unknown })
                  ? "#64748b" : "rgba(203, 213, 225, 0.15)";
              }}
              linkWidth={(l) =>
                linkTouchesFocus(l as { source: unknown; target: unknown }) ? 2 : 1}
              onNodeHover={(node) => setHover(node ? (node as unknown as KgNode).id : null)}
              onNodeClick={(node) => setSelected(node as unknown as KgNode)}
              onBackgroundClick={() => setSelected(null)}
            />
          )}
        </div>
      </div>

      {selected && (
        // 모바일: 캔버스를 덮는 바텀 시트 / 데스크톱: 우측 고정 패널
        <aside className="fixed inset-x-0 bottom-0 z-20 max-h-[55%] overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl
          md:static md:z-auto md:max-h-none md:w-80 md:shrink-0 md:rounded-none md:border-l md:border-slate-200 md:shadow-none">
          <div className="mx-auto mb-3 h-1 w-9 rounded-full bg-slate-300 md:hidden" />
          <div className="flex items-start justify-between">
            <div className="text-xs font-semibold text-slate-400">노드 상세</div>
            <button onClick={() => setSelected(null)} aria-label="닫기"
              className="-mt-1 px-2 text-slate-400 hover:text-blue-600 md:hidden"><X size={16} strokeWidth={2} aria-hidden="true" /></button>
          </div>
          <span className={`mt-3 inline-block rounded-full px-2 py-0.5 text-xs ${KIND_CHIP[selected.kind]}`}>
            {KIND_LABEL[selected.kind]}{selected.status === "temp" ? " · 미연결 표기" : ""}
          </span>
          <div className="mt-2 break-words text-lg font-bold">{selected.full}</div>
          {selected.label_ko && <div className="text-sm text-slate-500">{selected.label_ko}</div>}

          {selectedRec ? (
            <div className="mt-4 space-y-3 text-sm">
              <div><span className="text-slate-400">날짜</span> {selectedRec.date}</div>
              {selectedRec.objective && <div><span className="text-slate-400">목적</span> {selectedRec.objective}</div>}
              {selectedRec.symptom.category !== "none" && (
                <div><span className="text-slate-400">증상</span> {selectedRec.symptom.description}</div>
              )}
              <button onClick={() => nav(`/notes/${selectedRec.id}`)}
                className="w-full rounded-lg bg-blue-600 py-2 text-sm text-white hover:bg-blue-700">
                기록 열기
              </button>
            </div>
          ) : (
            <div className="mt-4">
              <div className="flex gap-6 text-sm">
                <div><div className="text-slate-400">연결된 실험</div><div className="font-bold">{related.length}건</div></div>
                <div>
                  <div className="text-slate-400">확정 사례</div>
                  <div className="font-bold">{related.filter((r) => r.resolution.resolved).length}건</div>
                </div>
              </div>
              <div className="mt-4 text-xs font-semibold text-slate-400">관련 기록</div>
              <div className="mt-2 space-y-2">
                {related.map((r) => (
                  <RecordCard key={r.id} meta={r} onClick={() => nav(`/notes/${r.id}`)} />
                ))}
              </div>
            </div>
          )}
        </aside>
      )}
    </div>
  );
}
