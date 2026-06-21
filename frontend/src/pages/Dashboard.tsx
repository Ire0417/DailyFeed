import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useReports } from "../hooks/useReports";
import { useSubscriptions } from "../hooks/useSubscriptions";
import { reportService } from "../services/report";

const Dashboard: React.FC = () => {
  const { user, refresh: refreshUser } = useAuth();
  const { items: reports, loading: reportsLoading, reload: reloadReports } = useReports();
  const { items: subs, loading: subsLoading, reload: reloadSubs } = useSubscriptions();
  const [runBusy, setRunBusy] = useState(false);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    if (user?.isLoggedIn) {
      reloadReports();
      reloadSubs();
      refreshUser();
    }
  }, [user?.isLoggedIn]);

  const onRun = async () => {
    setRunBusy(true);
    setRunMsg(null);
    setRunError(null);
    try {
      const res = await (reportService.runNow() as Promise<any>);
      setRunMsg(res?.message || "已触发生成");
      setTimeout(() => reloadReports(), 500);
    } catch (err: any) {
      setRunError(err?.message || "触发失败，请稍后重试");
    } finally {
      setRunBusy(false);
    }
  };

  const stats = {
    subsTotal: subs.length,
    subsActive: subs.filter((s: any) => s.is_active).length,
    reportsTotal: reports.length,
    latestDate: reports[0]?.report_date || null,
  };

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div className="bg-white border rounded-2xl p-8 relative">
        <div className="relative z-10">
          <h1 className="text-3xl font-semibold text-slate-900 mb-2">
            你好，{user?.username || "访客"} 👋
          </h1>
          <p className="text-slate-500 mb-6">
            每日摘要将为你聚合你订阅的 RSS、GitHub 项目、B 站动态，并生成精炼报告发送到邮箱。
          </p>
          <button
            onClick={onRun}
            disabled={runBusy}
            className="inline-flex items-center gap-2 px-5 py-2.5 bg-slate-900 text-white rounded-lg hover:bg-slate-800 disabled:opacity-50 transition font-medium"
          >
            {runBusy ? (
              <>正在生成中...</>
            ) : (
              <>⚡ 立即生成一次</>
            )}
          </button>
          {runMsg && (
            <div className="mt-4 text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-lg px-4 py-2.5">
              {runMsg}
            </div>
          )}
          {runError && (
            <div className="mt-4 text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-2.5">
              {runError}
            </div>
          )}
        </div>
        <div className="absolute right-0 top-0 text-[160px] opacity-5 select-none pointer-events-none">📨</div>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white border rounded-xl p-5">
          <div className="text-slate-500 text-xs font-medium">订阅源总数</div>
          <div className="text-3xl font-semibold mt-2 text-slate-900">{stats.subsTotal}</div>
          <div className="text-xs text-slate-500 mt-1">{stats.subsActive} 个活跃</div>
        </div>
        <div className="bg-white border rounded-xl p-5">
          <div className="text-slate-500 text-xs font-medium">已生成报告</div>
          <div className="text-3xl font-semibold mt-2 text-slate-900">{stats.reportsTotal}</div>
          <div className="text-xs text-slate-500 mt-1">
            {stats.latestDate ? `最近：${stats.latestDate}` : "尚未生成"}
          </div>
        </div>
        <div className="bg-white border rounded-xl p-5">
          <div className="text-slate-500 text-xs font-medium">活跃订阅源</div>
          <div className="text-3xl font-semibold mt-2 text-slate-900">{stats.subsActive}</div>
          <div className="text-xs text-slate-500 mt-1">下次生成时会抓取</div>
        </div>
        <div className="bg-white border rounded-xl p-5">
          <div className="text-slate-500 text-xs font-medium">推送渠道</div>
          <div className="text-3xl font-semibold mt-2 text-slate-900">
            {(user?.settings?.channels || ["email"]).length}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {(user?.settings?.channels || ["email"]).join(", ")}
          </div>
        </div>
      </div>

      {/* Two column main */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Recent reports */}
        <div className="bg-white border rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">最近报告</h2>
            <Link to="/reports" className="text-sm text-slate-500 hover:text-slate-900">
              查看全部 →
            </Link>
          </div>
          {reportsLoading ? (
            <div className="text-slate-500 text-sm text-center py-8">加载中...</div>
          ) : reports.length === 0 ? (
            <div className="border border-dashed rounded-lg p-10 text-center text-slate-500 text-sm">
              暂无报告
              <div className="mt-3">
                <Link to="/subscriptions" className="text-slate-900 underline hover:text-slate-700">
                  添加订阅源
                </Link>
                <span className="mx-2 text-slate-300">·</span>
                或点击 <span className="font-medium text-slate-900">立即生成一次</span>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {reports.slice(0, 5).map((r: any) => (
                <Link
                  key={r.id}
                  to={`/reports/${r.id}`}
                  className="block border border-slate-100 hover:border-slate-300 hover:bg-slate-50 rounded-lg p-3 transition"
                >
                  <div className="flex items-center justify-between">
                    <div className="font-medium text-slate-900 text-sm truncate">{r.title}</div>
                    <span className="text-xs text-slate-500 whitespace-nowrap ml-2">{r.report_date}</span>
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    {r.stats?.total_items || 0} 条更新 · {r.stats?.total_sources || 0} 个订阅源
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Active subscriptions */}
        <div className="bg-white border rounded-xl p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">我的订阅源</h2>
            <Link to="/subscriptions" className="text-sm text-slate-500 hover:text-slate-900">
              管理 →
            </Link>
          </div>
          {subsLoading ? (
            <div className="text-slate-500 text-sm text-center py-8">加载中...</div>
          ) : subs.length === 0 ? (
            <div className="border border-dashed rounded-lg p-10 text-center text-slate-500 text-sm">
              还没有订阅源
              <div className="mt-3">
                <Link to="/subscriptions" className="text-slate-900 underline hover:text-slate-700">
                  添加你的第一个订阅源
                </Link>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {subs.slice(0, 5).map((s: any) => (
                <div key={s.id} className="border border-slate-100 rounded-lg p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={`inline-block w-2 h-2 rounded-full ${s.is_active ? "bg-emerald-500" : "bg-slate-300"}`}></span>
                      <span className="text-sm font-medium text-slate-900">{s.source_type.toUpperCase()}</span>
                    </div>
                    <span className="text-xs text-slate-500">优先级 {s.priority}</span>
                  </div>
                  <div className="text-sm text-slate-600 mt-1.5 truncate font-mono text-xs">{s.source_url}</div>
                  <div className="text-xs text-slate-400 mt-1">
                    最近抓取：{s.last_fetch_at ? new Date(s.last_fetch_at).toLocaleString() : "尚未"}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
