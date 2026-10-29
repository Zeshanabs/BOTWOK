/**
 * Botwok API client. Same-origin (/api/* is proxied to FastAPI by next.config rewrites), JSON,
 * RFC 9457 Problem Details errors, bearer token from the session store, X-Workspace-Id header,
 * and a single automatic refresh on 401.
 */
import { membershipsFrom, useSession } from "@/stores/session";

export interface Problem {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  errors?: { code?: string; field?: string; message?: string }[];
}

export class ApiError extends Error {
  problem: Problem;
  constructor(problem: Problem) {
    super(problem.detail || problem.title);
    this.problem = problem;
  }
  get status() {
    return this.problem.status;
  }
  get code() {
    return this.problem.type?.split("/").pop() || "error";
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

let refreshing: Promise<boolean> | null = null;

export async function refreshSession(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const res = await fetch("/api/v1/auth/refresh", { method: "POST", credentials: "include" });
        if (!res.ok) return false;
        const data = await res.json();
        useSession.getState().setAuth(data.access_token, data.user, membershipsFrom(data));
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

async function request<T>(method: Method, path: string, body?: unknown, opts: { retry?: boolean; raw?: boolean } = {}): Promise<T> {
  const { accessToken, workspaceId } = useSession.getState();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (workspaceId) headers["X-Workspace-Id"] = workspaceId;
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: "include",
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
  });
  if (res.status === 401 && opts.retry !== false && !path.startsWith("/auth/")) {
    if (await refreshSession()) return request<T>(method, path, body, { ...opts, retry: false });
    useSession.getState().clear();
  }
  if (!res.ok) {
    let problem: Problem;
    try {
      problem = await res.json();
    } catch {
      problem = { type: "http_error", title: res.statusText, status: res.status };
    }
    throw new ApiError(problem);
  }
  if (res.status === 204) return undefined as T;
  if (opts.raw) return (await res.blob()) as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  get: <T,>(path: string) => request<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T,>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T,>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  delete: <T,>(path: string) => request<T>("DELETE", path),
};

export function qs(params: Record<string, string | number | boolean | undefined | null | string[]>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, String(x)));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
