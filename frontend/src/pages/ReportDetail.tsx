import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { reportService } from "../services/report";

interface ReportDetailData {
  id: number;
  title: string;
  report_date: string;
  status: string;
  stats: { total_items?: number; total_sources?: number };
  created_at: string | null;
  markdown_body: string;
  html_body?: string;
}

const ReportDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [report, setReport] = useState<ReportDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    (async () => {
      setLoading(true);
      try {
        const r = await reportService.get(Number(id));
        setReport(r as any);
      } catch (err: any) {
        setError(err?.message || "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  if (loading) {
    return <div className="text-slate-500 text-center py-20">加载中...</div>;
  }
  if (error) {
    return (
      <div className="text-red-600 bg-red-50 border border-red-200 rounded-xl p-8 text-center">
        {error}
        <div className="mt-4">
          <Link to="/reports" className="text-slate-900 underline hover:text-slate-700">
            ← 返回报告列表
          </Link>
        </div>
      </div>
    );
  }
  if (!report) return null;

  // 简易 Markdown 渲染（若后端没有 html_body，用 markdown_body 直接格式化）
  const bodyToRender: string = report.html_body || "";

  return (
    <div className="space-y-6">
      <div>
        <Link to="/reports" className="text-sm text-slate-500 hover:text-slate-900">
          ← 返回报告列表
        </Link>
      </div>

      <div className="bg-white border rounded-2xl p-8">
        <div className="text-sm text-slate-500 mb-2">{report.report_date}</div>
        <h1 className="text-3xl font-semibold text-slate-900">{report.title}</h1>
        <div className="mt-4 flex flex-wrap gap-3 text-sm text-slate-500">
          <span className="px-3 py-1 rounded-full bg-slate-50 border border-slate-200">
            {report.stats?.total_items || 0} 条内容
          </span>
          <span className="px-3 py-1 rounded-full bg-slate-50 border border-slate-200">
            来自 {report.stats?.total_sources || 0} 个订阅源
          </span>
          <span className="px-3 py-1 rounded-full bg-slate-50 border border-slate-200">
            状态：{report.status || "ready"}
          </span>
          <span className="px-3 py-1 rounded-full bg-slate-50 border border-slate-200">
            生成于 {report.created_at ? new Date(report.created_at).toLocaleString() : "N/A"}
          </span>
        </div>
      </div>

      <div className="bg-white border rounded-2xl p-8">
        {bodyToRender ? (
          <div
            className="prose prose-slate max-w-none"
            dangerouslySetInnerHTML={{ __html: bodyToRender }}
          />
        ) : (
          <pre className="whitespace-pre-wrap text-slate-800 leading-relaxed text-sm font-sans">
            {report.markdown_body || "(空报告)"}
          </pre>
        )}
      </div>
    </div>
  );
};

export default ReportDetail;
