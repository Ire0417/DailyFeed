export type SourceType = "rss" | "github" | "bilibili";

export interface SubscriptionType {
  id: number;
  source_type: SourceType;
  source_url: string;
  priority: number;
  is_active: boolean;
  config: Record<string, any>;
  last_fetch_at: string | null;
  created_at: string | null;
}

// 兼容别名：项目中部分代码用 Subscription 类型名
export type Subscription = SubscriptionType;

