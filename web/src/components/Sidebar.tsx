import { useState } from "react";
import { Ellipsis, NotebookText, Pencil, Pin, PinOff, Plus, Settings, Sparkles, Trash2, Network, Workflow, Library } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import Logo from "./Logo";
import { useNav } from "../nav";
import { deleteSession, listSessions, saveSession } from "../store";
import type { Session } from "../types";

function sessionPath(s: Session): string {
  if (s.kind === "ask") return `/ask/${s.id}`;
  if (s.kind === "followup") return `/followup/${s.id}`;
  return `/log/${s.id}`;
}

const LINKS = [
  { to: "/", icon: Sparkles, label: "AI 워크스페이스", match: (p: string) => p === "/" },
  { to: "/notes", icon: NotebookText, label: "연구노트", match: (p: string) => p.startsWith("/notes") },
  { to: "/graph", icon: Network, label: "그래프뷰", match: (p: string) => p.startsWith("/graph") },
  { to: "/flow", icon: Workflow, label: "워크플로", match: (p: string) => p.startsWith("/flow") },
  { to: "/domains", icon: Library, label: "연구 도메인", match: (p: string) => p.startsWith("/domains") },
];

export default function Sidebar() {
  const nav = useNavigate();
  const loc = useLocation();
  const { open, setOpen } = useNav();
  const { mode, me, signOut } = useAuth();
  const close = () => setOpen(false);
  // 세션 메뉴 상태 — 목록은 localStorage에서 매 렌더 읽으므로 조작 후 rev만 올리면 갱신된다
  const [, setRev] = useState(0);
  const bump = () => setRev((r) => r + 1);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameText, setRenameText] = useState("");

  function togglePin(s: Session) {
    s.pinned = !s.pinned;
    saveSession(s);
    setMenuFor(null);
    bump();
  }
  function startRename(s: Session) {
    setRenaming(s.id);
    setRenameText(s.title);
    setMenuFor(null);
  }
  function commitRename(s: Session) {
    if (renameText.trim()) {
      s.title = renameText.trim();
      saveSession(s);
    }
    setRenaming(null);
    bump();
  }
  function removeSession(s: Session) {
    setMenuFor(null);
    if (!window.confirm(`'${s.title}' 대화를 삭제할까요?`)) return;
    deleteSession(s.id);
    if (loc.pathname.includes(s.id)) nav("/");
    bump();
  }

  const links = me?.role === "admin"
    ? [...LINKS, { to: "/settings", icon: Settings, label: "연구실 설정",
                   match: (p: string) => p.startsWith("/settings") }]
    : LINKS;
  const sessions = listSessions();
  const today = new Date().toDateString();
  const isToday = (s: Session) => new Date(s.createdAt).toDateString() === today;

  const navLinks = (dark: boolean) =>
    links.map((l) => (
      <Link key={l.to} to={l.to} onClick={close}
        className={`flex items-center gap-2 rounded px-3 py-2 text-sm ${dark
          ? (l.match(loc.pathname) ? "bg-slate-700 text-sky-300" : "text-slate-300 hover:bg-slate-800 hover:text-slate-100")
          : (l.match(loc.pathname) ? "bg-blue-50 font-medium text-blue-700" : "text-slate-700 hover:bg-slate-100")}`}>
        <l.icon aria-hidden strokeWidth={2} size={20} />
        {l.label}
      </Link>
    ));

  const group = (list: Session[], label: string) =>
    list.length > 0 && (
      <div className="mt-4">
        <div className="px-3 text-xs text-slate-400">{label}</div>
        {list.map((s) => (
          <div key={s.id} className="group/row relative">
            {renaming === s.id ? (
              <input autoFocus value={renameText} onChange={(e) => setRenameText(e.target.value)}
                onBlur={() => commitRename(s)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) commitRename(s);
                  if (e.key === "Escape") setRenaming(null);
                }}
                className="w-full rounded border border-blue-400 px-3 py-2 text-sm outline-none" />
            ) : (
              <Link to={sessionPath(s)} onClick={close}
                className={`block truncate rounded px-3 py-2 pr-8 text-sm ${
                  loc.pathname.includes(s.id) ? "bg-blue-50 text-blue-700" : "text-slate-700 hover:bg-slate-100"}`}>
                {s.pinned && <Pin aria-hidden strokeWidth={2} size={14} className="mr-1 inline-block text-slate-500" />}{s.title}
              </Link>
            )}
            {renaming !== s.id && (
              <button onClick={() => setMenuFor(menuFor === s.id ? null : s.id)} aria-label="세션 메뉴"
                className="absolute right-1 top-1/2 -translate-y-1/2 rounded px-1.5 text-slate-400
                  hover:bg-slate-200 hover:text-blue-600 md:opacity-0 md:group-hover/row:opacity-100"><Ellipsis aria-hidden strokeWidth={2} size={16} /></button>
            )}
            {menuFor === s.id && (
              <div className="absolute right-1 top-8 z-[60] w-36 rounded-lg border border-slate-200 bg-white py-1 text-sm shadow-lg">
                <button onClick={() => togglePin(s)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-50">
                  {s.pinned ? <PinOff aria-hidden strokeWidth={2} size={16} /> : <Pin aria-hidden strokeWidth={2} size={16} />} {s.pinned ? "고정 해제" : "고정"}
                </button>
                <button onClick={() => startRename(s)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-50"><Pencil aria-hidden strokeWidth={2} size={16} />이름 변경</button>
                <button onClick={() => removeSession(s)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-red-600 hover:bg-red-50"><Trash2 aria-hidden strokeWidth={2} size={16} />삭제</button>
              </div>
            )}
          </div>
        ))}
      </div>
    );

  return (
    <>
      {open && (
        <div onClick={close} aria-hidden
          className="fixed inset-0 z-30 bg-slate-900/45 md:hidden" />
      )}
      {/* 세션 메뉴 바깥 클릭 닫기 — 메뉴(z-50)보다 아래 */}
      {menuFor && <div onClick={() => setMenuFor(null)} aria-hidden className="fixed inset-0 z-50" />}
      {/* 모바일: 좌측 오버레이 드로어 / 데스크톱: 다크 레일 + 세션 목록 2단 고정.
          닫힘은 translate가 아니라 hidden — 화면 밖 요소가 남지 않아 터치·탭 순서도 깨끗하다. */}
      <div className={`fixed inset-y-0 left-0 z-40 w-4/5 max-w-xs shadow-2xl
        md:static md:z-auto md:flex md:h-screen md:w-auto md:max-w-none md:shadow-none
        ${open ? "flex" : "hidden"}`}>
        <nav className="hidden w-52 shrink-0 flex-col gap-1 bg-slate-900 p-4 text-slate-200 md:flex">
          <div className="mb-8 flex items-center gap-2 font-bold tracking-wide">
            <Logo className="h-8 w-8" />
            <span>LAB <span className="text-sky-400">GENE</span></span>
          </div>
          {navLinks(true)}
          {mode === "deploy" && me?.lab && (
            <div className="mt-auto border-t border-slate-700 pt-3 text-sm">
              <div className="truncate font-medium text-slate-200">{me.lab.name}</div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">{me.role === "admin" ? "관리자" : "멤버"}</span>
                <button onClick={() => void signOut()}
                  className="text-xs text-slate-500 underline hover:text-slate-300">로그아웃</button>
              </div>
            </div>
          )}
        </nav>

        <aside className="flex min-w-0 flex-1 flex-col bg-white md:w-60 md:flex-none md:border-r md:border-slate-200">
          <div className="flex items-center gap-2 bg-slate-900 px-4 py-3 font-bold tracking-wide text-white md:hidden">
            <Logo className="h-7 w-7" />
            <span>LAB <span className="text-sky-400">GENE</span></span>
          </div>
          <div className="p-3">
            <button onClick={() => { close(); nav("/"); }}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700">
              <Plus aria-hidden strokeWidth={2} size={16} />새 대화
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
            {group(sessions.filter(isToday), "오늘")}
            {group(sessions.filter((s) => !isToday(s)), "이전")}
          </div>
          <div className="flex flex-col gap-1 border-t border-slate-200 p-3 md:hidden">
            {navLinks(false)}
          </div>
          {/* 데스크톱은 다크 레일 하단으로 이동 — 모바일 드로어에서만 표시 */}
          {mode === "deploy" && me?.lab && (
            <div className="border-t border-slate-200 p-3 md:hidden">
              <div className="truncate text-sm font-medium">{me.lab.name}</div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">{me.role === "admin" ? "관리자" : "멤버"}</span>
                <button onClick={() => void signOut()} className="text-xs text-slate-400 underline">
                  로그아웃
                </button>
              </div>
            </div>
          )}
        </aside>
      </div>
    </>
  );
}
