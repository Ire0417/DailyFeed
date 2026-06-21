import { useEffect, useState, useCallback } from "react";
import { reportService } from "../services/report";
import type { Report } from "../types/report";

type Listener = (items: Report[]) => void;
type StatusListener = (loading: boolean, error: string | null) => void;

const listeners = new Set<Listener>();
const statusListeners = new Set<StatusListener>();
let items: Report[] = [];
let loading = false;
let error: string | null = null;

function notify() { listeners.forEach((fn) => fn(items)); }
function notifyStatus() { statusListeners.forEach((fn) => fn(loading, error)); }

export const reportStore = {
  get(): Report[] { return items; },
  subscribe(fn: Listener) { listeners.add(fn); return () => { listeners.delete(fn); }; },
  subscribeStatus(fn: StatusListener) { statusListeners.add(fn); return () => { statusListeners.delete(fn); }; },
  async load() {
    loading = true; error = null; notifyStatus();
    try {
      items = await reportService.list();
      notify();
    } catch (err: any) {
      error = err?.message || "加载失败";
    } finally {
      loading = false; notifyStatus();
    }
  },
  async runNow() {
    const res = await reportService.runNow();
    return res;
  },
};

export function useReports() {
  const [data, setData] = useState<Report[]>(items);
  const [busy, setBusy] = useState<boolean>(loading);
  const [err, setErr] = useState<string | null>(error);
  useEffect(() => reportStore.subscribe(setData), []);
  useEffect(() => reportStore.subscribeStatus((l, e) => { setBusy(l); setErr(e); }), []);
  const reload = useCallback(() => reportStore.load(), []);
  return { items: data, loading: busy, error: err, reload };
}
