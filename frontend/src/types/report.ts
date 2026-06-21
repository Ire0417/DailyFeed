export interface Report {
  id: number;
  report_date: string;
  title: string;
  status: "ready" | "delivered" | "draft";
  stats: { total_items?: number; total_sources?: number };
  created_at: string | null;
  delivered_at: string | null;
  markdown_body?: string;
  html_body?: string;
}

export interface ReportListItem extends Report {}
