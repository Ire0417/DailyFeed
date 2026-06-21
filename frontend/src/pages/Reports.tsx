import React, { useEffect } from "react";
import { Link } from "react-router-dom";
import { useReports } from "../hooks/useReports";

const Reports: React.FC = () => {
  const { items, loading, reload } = useReports();
  useEffect(() => { reload(); }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold">报告列表</h1>
          <p className="text-slate-500 text-sm mt-1">历史生成的摘要报告。点击查看详情。</p>
        </div>
        <button onClick={reload} className="text-sm text-slate-500 hover:text-slate-900">
          🔄 刷新
        </button>
      </div>

      {loading ? (
        <div className="text-slate-500 text-sm text-center py-20">加载中...</div>
      ) : items.length === 0 ? (
        <div className="border border-dashed rounded-2xl p-20 text-center text-slate-500">
          <div className="text-5xl mb-4 opacity-40">📋</div>
          <div className="text-lg font-medium text-slate-700 mb-2">还没有报告</div>
          <div className="text-sm">
            去 <Link to="/subscriptions" className="text-slate-900 underline">添加订阅源</Link>
            ，或回到 <Link to="/" className="text-slate-900 underline">首页</Link> 点击「立即生成一次」。
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((r: any) => (
            <Link
              key={r.id}
              to={`/reports/${r.id}`}
              className="block bg-white border border-slate-100 hover:shadow-sm border rounded-2xl p-5 transition hover:border-slate-300"
            >
              <div className="flex items-start justify-between gap-6">
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-slate-900 text-lg mb-1">{r.title}</div>
                  <div className="text-sm text-slate-500">
                    {r.report_date} · {r.stats?.total_items || 0} 条更新 · 来自 {r.stats?.total_sources || 0} 个订阅源
                  </div>
                  <div className="text-xs text-slate-400 mt-2">
                    生成于 {r.created_at ? new Date(r.created_at).toLocaleString() : "N/A"}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <div className="text-sm text-slate-500">状态</div>
                  <div className="text-xs px-2 py-1 bg-emerald-50 text-emerald-700 rounded">
                    {r.status || "ready"}
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
};

export default Reports;
