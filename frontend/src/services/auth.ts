import { api } from "./api";

export interface AuthUser {
  id: number;
  username: string;
  email: string;
}

export interface AuthResult {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export const authService = {
  register(username: string, email: string, password: string) {
    return api.post<AuthResult>("/auth/register", { username, email, password });
  },
  login(email: string, password: string) {
    return api.post<AuthResult>("/auth/login", { email, password });
  },
  me() {
    return api.get<AuthUser & { settings: Record<string, any>; last_login_at: string | null }>("/auth/me");
  },
  saveToken(token: string) {
    try { localStorage.setItem("df_token", token); } catch {}
  },
  clearToken() {
    try { localStorage.removeItem("df_token"); } catch {}
  },
  hasToken() {
    try { return !!localStorage.getItem("df_token"); } catch { return false; }
  },
};
