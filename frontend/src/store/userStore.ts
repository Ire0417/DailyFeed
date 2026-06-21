/** 简单的 zustand 风格状态管理（不依赖外部库，避免在 MVP 阶段引入新依赖）。 */
import { useEffect, useState, useCallback } from "react";
import { authService } from "../services/auth";

export interface UserState {
  id: number | null;
  username: string | null;
  email: string | null;
  settings: Record<string, any>;
  isLoggedIn: boolean;
}

const initialState: UserState = {
  id: null,
  username: null,
  email: null,
  settings: {},
  isLoggedIn: false,
};

type Listener = (state: UserState) => void;
const listeners = new Set<Listener>();
let current: UserState = initialState;

function setState(partial: Partial<UserState>) {
  current = { ...current, ...partial };
  listeners.forEach((fn) => fn(current));
}

export const userStore = {
  get(): UserState {
    return current;
  },
  subscribe(fn: Listener): () => void {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
  async login(email: string, password: string) {
    const res = await authService.login(email, password);
    authService.saveToken(res.access_token);
    setState({ id: res.user.id, username: res.user.username, email: res.user.email, isLoggedIn: true });
    return res;
  },
  async register(username: string, email: string, password: string) {
    const res = await authService.register(username, email, password);
    authService.saveToken(res.access_token);
    setState({ id: res.user.id, username: res.user.username, email: res.user.email, isLoggedIn: true });
    return res;
  },
  async refresh() {
    if (!authService.hasToken()) return null;
    try {
      const me = await authService.me();
      setState({ id: me.id, username: me.username, email: me.email, settings: me.settings || {}, isLoggedIn: true });
      return me;
    } catch {
      setState(initialState);
      authService.clearToken();
      return null;
    }
  },
  logout() {
    authService.clearToken();
    setState(initialState);
  },
  setSettings(settings: Record<string, any>) {
    setState({ settings });
  },
};

export function useUser(): [UserState, typeof userStore] {
  const [state, setLocal] = useState<UserState>(current);
  useEffect(() => userStore.subscribe(setLocal), []);
  return [state, userStore];
}

export function useAuthenticated() {
  const [state] = useUser();
  return state.isLoggedIn;
}

// Auto log-out on 401 events handled by api.ts
if (typeof window !== "undefined") {
  window.addEventListener("df:logout", () => userStore.logout());
}

// Subscription store (similar pattern)
import { subscriptionService, Subscription } from "../services/subscription";

type SubListener = (items: Subscription[]) => void;
const subListeners = new Set<SubListener>();
let subItems: Subscription[] = [];
let subLoading = false;
let subError: string | null = null;
const statusListeners = new Set<(loading: boolean, error: string | null) => void>();

function notifySubs() { subListeners.forEach((fn) => fn(subItems)); }
function notifyStatus() { statusListeners.forEach((fn) => fn(subLoading, subError)); }

export const subscriptionStore = {
  get(): Subscription[] { return subItems; },
  subscribe(fn: SubListener) { subListeners.add(fn); return () => { subListeners.delete(fn); }; },
  subscribeStatus(fn: (loading: boolean, error: string | null) => void) {
    statusListeners.add(fn); return () => { statusListeners.delete(fn); };
  },
  async load() {
    subLoading = true; subError = null; notifyStatus();
    try {
      subItems = await subscriptionService.list();
      notifySubs();
    } catch (err: any) {
      subError = err?.message || "加载失败";
    } finally {
      subLoading = false; notifyStatus();
    }
  },
  async create(body: { source_type: string; source_url: string; priority?: number }) {
    const item = await subscriptionService.create(body);
    subItems = [item, ...subItems];
    notifySubs();
    return item;
  },
  async update(id: number, body: Partial<Subscription>) {
    const item = await subscriptionService.update(id, body);
    subItems = subItems.map((s) => (s.id === id ? item : s));
    notifySubs();
    return item;
  },
  async remove(id: number) {
    await subscriptionService.remove(id);
    subItems = subItems.filter((s) => s.id !== id);
    notifySubs();
  },
  async toggle(id: number, is_active: boolean) {
    const item = await subscriptionService.toggle(id, is_active);
    subItems = subItems.map((s) => (s.id === id ? item : s));
    notifySubs();
    return item;
  },
};

export function useSubscriptions() {
  const [items, setItems] = useState<Subscription[]>(subItems);
  const [loading, setLoading] = useState<boolean>(subLoading);
  const [error, setError] = useState<string | null>(subError);
  useEffect(() => subscriptionStore.subscribe(setItems), []);
  useEffect(() => subscriptionStore.subscribeStatus((l, e) => { setLoading(l); setError(e); }), []);
  const reload = useCallback(() => subscriptionStore.load(), []);
  return { items, loading, error, reload };
}
