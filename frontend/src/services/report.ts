import { api } from "../services/api";
import type { Report } from "../types/report";

export const reportService = {
  list() {
    return api.get<Report[]>("/reports");
  },
  get(id: number) {
    return api.get<Report>(`/reports/${id}`);
  },
  runNow() {
    return api.post<{ ok: boolean; message: string }>("/reports/run-now");
  },
};
