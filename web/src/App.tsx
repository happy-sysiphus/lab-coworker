import { Fragment, type ReactNode } from "react";
import { HashRouter, Route, Routes, useParams } from "react-router-dom";
import { AuthProvider, resolveRoute, useAuth } from "./auth";
import Sidebar from "./components/Sidebar";
import { NavProvider } from "./nav";
import Ask from "./pages/Ask";
import Flow from "./pages/Flow";
import FollowUp from "./pages/FollowUp";
import Graph from "./pages/Graph";
import Home from "./pages/Home";
import LogChat from "./pages/LogChat";
import Login from "./pages/Login";
import Notes from "./pages/Notes";
import Onboarding from "./pages/Onboarding";
import Preview from "./pages/Preview";
import Settings from "./pages/Settings";

// 같은 route 안에서 :sid만 바뀌면 React가 컴포넌트를 remount하지 않아 훅 내부 세션 상태와
// 자동 시작 가드가 이전 세션에 남는다. key로 세션마다 강제 remount.
function BySid({ children }: { children: ReactNode }) {
  const { sid } = useParams();
  return <Fragment key={sid}>{children}</Fragment>;
}

// 로그인·온보딩은 라우트가 아니라 앱 셸 자체를 대체한다 — 어느 해시 경로로 들어와도 같게 걸린다
function Gate({ children }: { children: ReactNode }) {
  const { mode, session, me } = useAuth();
  const route = resolveRoute(mode, !!session, !!me?.lab);
  if (route === "loading")
    return <div className="flex h-screen items-center justify-center text-slate-400">불러오는 중...</div>;
  if (route === "login") return <Login />;
  if (route === "onboarding") return <Onboarding />;
  return <>{children}</>;
}

export default function App() {
  return (
    <HashRouter>
      <AuthProvider>
      <Gate>
      <NavProvider>
      <div className="flex h-screen bg-slate-50 text-slate-900">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/log/:sid" element={<BySid><LogChat /></BySid>} />
            <Route path="/ask/:sid" element={<BySid><Ask /></BySid>} />
            <Route path="/preview/:sid" element={<Preview />} />
            <Route path="/graph" element={<Graph />} />
            <Route path="/flow" element={<Flow />} />
            <Route path="/notes" element={<Notes />} />
            <Route path="/notes/:id" element={<Notes />} />
            <Route path="/followup/:sid" element={<BySid><FollowUp /></BySid>} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
      </NavProvider>
      </Gate>
      </AuthProvider>
    </HashRouter>
  );
}
