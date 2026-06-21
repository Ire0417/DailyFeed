/** API 基础封装：带 token、错误处理、超时。 */
export interface RequestOptions extends RequestInit {
  timeoutMs?: number;
  auth?: boolean; // default true
  params?: Record<string, string | number | boolean | undefined>;
}

const API_BASE = (import.meta as any).env?.VITE_API_BASE || "/api";

function getToken(): string | null {
  try {
    return localStorage.getItem("df_token");
  } catch {
    return null;
  }
}

export async function request<T = any>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { timeoutMs = 15000, auth = true, params, headers, body, ...rest } = opts;

  let url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  if (params) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) qs.append(k, String(v));
    });
    const q = qs.toString();
    if (q) url += `?${q}`;
  }

  const mergedHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string> | undefined),
  };
  if (auth) {
    const token = getToken();
    if (token) mergedHeaders["Authorization"] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(url, {
      ...rest,
      headers: mergedHeaders,
      body: body instanceof FormData || body === undefined || body === null ? body : JSON.stringify(body),
      signal: controller.signal,
    });
    if (res.status === 401) {
      try { localStorage.removeItem("df_token"); } catch {}
      window.dispatchEvent(new CustomEvent("df:logout"));
      throw new Error("未授权，请重新登录");
    }
    const contentType = res.headers.get("content-type") || "";
    const data = contentType.includes("application/json") ? await res.json() : await res.text();
    if (!res.ok) {
      const msg = typeof data === "object" && (data as any)?.detail ? String((data as any).detail) : `请求失败：${res.status}`;
      throw new Error(msg);
    }
    return data as T;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  get: <T = any>(path: string, opts?: RequestOptions) => request<T>(path, { ...opts, method: "GET" }),
  post: <T = any>(path: string, body?: any, opts?: RequestOptions) => request<T>(path, { ...opts, method: "POST", body }),
  put: <T = any>(path: string, body?: any, opts?: RequestOptions) => request<T>(path, { ...opts, method: "PUT", body }),
  delete: <T = any>(path: string, opts?: RequestOptions) => request<T>(path, { ...opts, method: "DELETE" }),
};

export { API_BASE };
