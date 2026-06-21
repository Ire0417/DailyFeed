import { api } from "./api";

export interface Subscription {
  id: number;
  source_type: "rss" | "github" | "bilibili";
  source_url: string;
  priority: number;
  is_active: boolean;
  config: Record<string, any>;
  last_fetch_at: string | null;
  created_at: string | null;
}

export const subscriptionService = {
  list() {
    return api.get<Subscription[]>("/subscriptions");
  },
  create(body: { source_type: string; source_url: string; priority?: number; config?: Record<string, any> }) {
    return api.post<Subscription>("/subscriptions", body);
  },
  update(id: number, body: Partial<Subscription>) {
    return api.put<Subscription>(`/subscriptions/${id}`, body);
  },
  remove(id: number) {
    return api.delete(`/subscriptions/${id}`);
  },
  toggle(id: number, is_active: boolean) {
    return api.post<Subscription>(`/subscriptions/${id}/toggle`, { is_active });
  },
};
