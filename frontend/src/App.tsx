import React, { useEffect } from "react";
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
  Link,
  useNavigate,
  useLocation,
} from "react-router-dom";

import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Subscriptions from "./pages/Subscriptions";
import Reports from "./pages/Reports";
import ReportDetail from "./pages/ReportDetail";
import Settings from "./pages/Settings";
import { useAuth } from "./hooks/useAuth";

const NavBar: React.FC = () => {
  const location = useLocation();
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const pathname = location.pathname;
  const linkCls = (p: string) =>
    `px-3 py-2 rounded-md text-sm transition ${
      pathname === p || pathname.startsWith(p + "/")
        ? "bg-slate-900 text-white font-medium"
        : "text-slate-600 hover:bg-slate-100"
    }`;

  const handleLogout = () => {
    logout();
    nav("/login");
  };

  return (
    <header className="bg-white border-b sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-6 flex items-center justify-between h-16">
        <Link to="/" className="font-semibold text-slate-900 text-lg">
          📨 每日摘要
        </Link>
        <nav className="flex items-center gap-1">
          <Link to="/" className={linkCls("/")}>首页</Link>
          <Link to="/subscriptions" className={linkCls("/subscriptions")}>订阅</Link>
          <Link to="/reports" className={linkCls("/reports")}>报告</Link>
          <Link to="/settings" className={linkCls("/settings")}>设置</Link>
          <button
            onClick={handleLogout}
            className="ml-4 px-3 py-2 rounded-md text-sm text-red-600 hover:bg-red-50"
          >
            退出
          </button>
        </nav>
      </div>
    </header>
  );
};

const Protected: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  if (!user?.isLoggedIn) return <Navigate to="/login" replace />;
  return <>{children}</>;
};

const PublicOnly: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth();
  if (user?.isLoggedIn) return <Navigate to="/" replace />;
  return <>{children}</>;
};

const AppRoutes: React.FC = () => {
  const { user, refresh } = useAuth();
  useEffect(() => {
    if (!user?.isLoggedIn) {
      refresh().catch(() => {});
    }
  }, []); // 启动时若有本地 token，则自动登录

  return (
    <div className="min-h-screen bg-white">
      {user?.isLoggedIn && <NavBar />}
      <main className="py-8">
        <div className="max-w-6xl mx-auto px-6">
          <Routes>
            <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
            <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
            <Route path="/" element={<Protected><Dashboard /></Protected>} />
            <Route path="/subscriptions" element={<Protected><Subscriptions /></Protected>} />
            <Route path="/reports" element={<Protected><Reports /></Protected>} />
            <Route path="/reports/:id" element={<Protected><ReportDetail /></Protected>} />
            <Route path="/settings" element={<Protected><Settings /></Protected>} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
};

const App: React.FC = () => (
  <BrowserRouter>
    <AppRoutes />
  </BrowserRouter>
);

export default App;
