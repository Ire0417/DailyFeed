import { useEffect, useState, useCallback } from "react";
import { subscriptionService, Subscription } from "../services/subscription";

type Listener = (items: Subscription[]) => void;
type StatusListener = (loading: boolean, error: string | null) => void;
const listeners = new Set<Listener>();
const statusListeners = new Set<StatusListener>();
let items: Subscription[] = [];
let loading = false;
let error: string | null = null;

function notify() { listeners.forEach((fn) => fn(items)); }
function notifyStatus() { statusListeners.forEach((fn) => fn(loading, error)); }

export const subStore = {
  get(): Subscription[] { return items; },
  subscribe(fn: Listener) { listeners.add(fn); return () => { listeners.delete(fn); }; },
  subscribeStatus(fn: StatusListener) { statusListeners.add(fn); return () => { statusListeners.delete(fn); }; },
  async load() {
    loading = true; error = null; notifyStatus();
    try {
      items = await subscriptionService.list();
      notify();
    } catch (err: any) {
      error = err?.message || "加载失败";
    } finally {
      loading = false; notifyStatus();
    }
  },
  async create(body: { source_type: string; source_url: string; priority?: number }) {
    const item = await subscriptionService.create(body);
    items = [item, ...items]; notify();
    return item;
  },
  async update(id: number, body: Partial<Subscription>) {
    const item = await subscriptionService.update(id, body);
    items = items.map((s) => (s.id === id ? item : s)); notify();
    return item;
  },
  async remove(id: number) {
    await subscriptionService.remove(id);
    items = items.filter((s) => s.id !== id); notify();
  },
  async toggle(id: number, is_active: boolean) {
    const item = await subscriptionService.toggle(id, is_active);
    items = items.map((s) => (s.id === id ? item : s)); notify();
    return item;
  },
};

export function useSubscriptions() {
  const [data, setData] = useState<Subscription[]>(items);
  const [busy, setBusy] = useState<boolean>(loading);
  const [err, setErr] = useState<string | null>(error);
  useEffect(() => subStore.subscribe(setData), []);
  useEffect(() => subStore.subscribeStatus((l, e) => { setBusy(l); setErr(e); }), []);
  const reload = useCallback(() => subStore.load(), []);
  return { items: data, loading: busy, error: err, reload };
}
