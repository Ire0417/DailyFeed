import React, { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

const Login: React.FC = () => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { login } = useAuth();
  const nav = useNavigate();

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null); setLoading(true);
    try {
      await login(email.trim(), password);
      nav("/");
    } catch (err: any) {
      setError(err?.message || "登录失败，请检查邮箱和密码");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-white px-4">
      <div className="w-full max-w-md p-8 bg-white rounded-2xl shadow-sm border">
        <div className="text-center mb-8">
          <div className="text-4xl mb-2">📨</div>
          <h1 className="text-2xl font-semibold text-slate-900">登录</h1>
          <p className="text-slate-500 text-sm mt-1">欢迎回来 👋</p>
        </div>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="block text-sm text-slate-600 mb-1.5">邮箱</label>
            <input
              type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-2.5 border rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900/20 focus:border-slate-900"
              placeholder="you@example.com"
            />
          </div>
          <div>
            <label className="block text-sm text-slate-600 mb-1.5">密码</label>
            <input
              type="password" required minLength={6} value={password} onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-2.5 border rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900/20 focus:border-slate-900"
              placeholder="至少 6 位"
            />
          </div>
          {error && (
            <div className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3 py-2">{error}</div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="w-full px-4 py-2.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50 transition font-medium"
          >
            {loading ? "登录中..." : "登录"}
          </button>
          <div className="text-sm text-slate-500 text-center pt-2">
            还没有账号？
            <Link to="/register" className="text-slate-900 underline ml-1 hover:text-slate-700">注册</Link>
          </div>
        </form>
      </div>
    </div>
  );
};

export default Login;
