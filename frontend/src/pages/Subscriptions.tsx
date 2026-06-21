import React, { useEffect, useState } from "react";
import { useSubscriptions, subStore } from "../hooks/useSubscriptions";

const PRESETS = [
  { label: "GitHub · 日榜", type: "github", url: "trending:daily", hint: "今日 GitHub 最热项目" },
  { label: "GitHub · 周榜", type: "github", url: "trending:weekly", hint: "本周 GitHub 最热项目" },
  { label: "GitHub · 月榜", type: "github", url: "trending:monthly", hint: "本月 GitHub 最热项目" },
  { label: "GitHub · 全时间星标 (Python)", type: "github", url: "topstarred:100000/python", hint: "Python 生态最热门项目" },
  { label: "GitHub · 全时间星标 (JavaScript)", type: "github", url: "topstarred:100000/javascript", hint: "JS/TS 生态最热门项目" },
  { label: "B 站 · UP主", type: "bilibili", url: "UID: 粘贴 UP主 的 UID", hint: "例：520934274" },
];

const Subscriptions: React.FC = () => {
  const { items, loading, reload } = useSubscriptions();
  const [sourceType, setSourceType] = useState<"rss" | "github" | "bilibili">("github");
  const [url, setUrl] = useState("");
  const [priority, setPriority] = useState(3);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { reload(); }, []);

  const handlePreset = (preset: typeof PRESETS[0]) => {
    setSourceType(preset.type as any);
    setUrl(preset.url.includes("UID") ? "" : preset.url);
  };

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null); setBusy(true);
    try {
      await subStore.create({ source_type: sourceType, source_url: url.trim(), priority });
      setUrl("");
    } catch (error: any) {
      setErr(error?.message || "添加失败，请检查输入");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (id: number, active: boolean) => {
    try { await subStore.toggle(id, active); } catch (e: any) { setErr(e?.message || "操作失败"); }
  };

  const remove = async (id: number) => {
    if (!confirm("确定删除这个订阅源吗？")) return;
    try { await subStore.remove(id); } catch (e: any) { setErr(e?.message || "删除失败"); }
  };

  const typeLabel = (t: string) =>
    t === "rss" ? "RSS" : t === "github" ? "GitHub" : "Bilibili";

  return (
    <div className="space-y-8">
      {/* Page title */}
      <div>
        <h1 className="text-2xl font-semibold">订阅源管理</h1>
        <p className="text-slate-500 text-sm mt-1">添加你关注的 RSS、GitHub 项目或 B 站 UP主。每次生成报告时会抓取最新内容。</p>
      </div>

      {/* Quick presets */}
      <div className="bg-white border rounded-2xl p-6">
        <h2 className="text-lg font-semibold mb-1">⚡ 快速预设</h2>
        <p className="text-slate-500 text-sm mb-4">点击即可预填写常用订阅源类型和地址。</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {PRESETS.map((p, i) => (
            <button
              key={i}
              onClick={() => handlePreset(p)}
              className="text-left border border-slate-200 hover:border-slate-400 hover:bg-slate-50 rounded-xl p-4 transition"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium px-2 py-0.5 bg-slate-100 text-slate-700 rounded">{typeLabel(p.type)}</span>
                <span className="text-xs text-slate-400">点击添加</span>
              </div>
              <div className="font-medium text-slate-900 mt-2 text-sm">{p.label}</div>
              <div className="text-xs text-slate-500 mt-1">{p.hint}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Add new subscription form */}
      <div className="bg-white border rounded-2xl p-6">
        <h2 className="text-lg font-semibold mb-4">添加新订阅源</h2>
        <form onSubmit={add} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="md:col-span-1">
              <label className="block text-sm text-slate-600 mb-1.5">类型</label>
              <select
                value={sourceType}
                onChange={(e) => setSourceType(e.target.value as any)}
                className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900/20 focus:border-slate-900"
              >
                <option value="rss">RSS</option>
                <option value="github">GitHub</option>
                <option value="bilibili">Bilibili</option>
              </select>
            </div>
            <div className="md:col-span-2">
              <label className="block text-sm text-slate-600 mb-1.5">
                {sourceType === "rss" ? "RSS 地址 (URL)" :
                 sourceType === "github" ? "GitHub 表达式（如 trending:daily）" :
                 "Bilibili UP主 UID（纯数字）"}
              </label>
              <input
                required
                value={url} onChange={(e) => setUrl(e.target.value)}
                placeholder={
                  sourceType === "rss" ? "https://example.com/feed.xml" :
                  sourceType === "github" ? "trending:daily / topstarred:50000/python" :
                  "520934274"
                }
                className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900/20 focus:border-slate-900 font-mono text-sm"
              />
            </div>
            <div className="md:col-span-1">
              <label className="block text-sm text-slate-600 mb-1.5">优先级 (1-5)</label>
              <input
                type="number" min={1} max={5}
                value={priority}
                onChange={(e) => setPriority(Math.max(1, Math.min(5, Number(e.target.value))))}
                className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900/20 focus:border-slate-900"
              />
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div className="text-sm">
              {err ? (
                <span className="text-red-600">{err}</span>
              ) : (
                <span className="text-slate-500">数字越大，优先级越高（越靠前展示）</span>
              )}
            </div>
            <button
              type="submit"
              disabled={busy || !url.trim()}
              className="px-5 py-2.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50 transition font-medium"
            >
              {busy ? "添加中..." : "✓ 添加订阅源"}
            </button>
          </div>
        </form>
      </div>

      {/* Subscription list */}
      <div className="bg-white border rounded-2xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">我的订阅 ({items.length})</h2>
          <button onClick={reload} className="text-sm text-slate-500 hover:text-slate-900">
            🔄 刷新
          </button>
        </div>

        {loading ? (
          <div className="text-slate-500 text-sm text-center py-10">加载中...</div>
        ) : items.length === 0 ? (
          <div className="border border-dashed rounded-lg p-14 text-center text-slate-500 text-sm">
            还没有订阅源，使用上方表单添加你的第一个订阅源吧。
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((s: any) => (
              <div key={s.id} className="border border-slate-200 rounded-xl p-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`inline-block w-2 h-2 rounded-full ${s.is_active ? "bg-emerald-500" : "bg-slate-300"}`}></span>
                      <span className="text-xs font-medium px-2 py-0.5 bg-slate-100 text-slate-700 rounded">
                        {typeLabel(s.source_type)}
                      </span>
                      <span className="text-xs text-slate-500">优先级 {s.priority}</span>
                    </div>
                    <div className="font-medium text-slate-900 font-mono text-sm break-all">
                      {s.source_url}
                    </div>
                    <div className="text-xs text-slate-500 mt-2">
                      {s.is_active ? "✅ 活跃" : "⏸ 已暂停"} · 最近抓取：
                      {s.last_fetch_at ? new Date(s.last_fetch_at).toLocaleString() : "尚未"}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => toggle(s.id, !s.is_active)}
                      className="px-3 py-1.5 text-sm rounded-lg border border-slate-200 text-slate-700 hover:bg-slate-50 transition"
                    >
                      {s.is_active ? "暂停" : "启用"}
                    </button>
                    <button
                      onClick={() => remove(s.id)}
                      className="px-3 py-1.5 text-sm rounded-lg border border-red-200 text-red-600 hover:bg-red-50 transition"
                    >
                      删除
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Subscriptions;
