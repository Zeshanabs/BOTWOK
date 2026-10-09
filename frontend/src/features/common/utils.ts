/** Small helpers shared by the content/ops features: list normalization, Problem Details mapping, formatting. */
import { formatDistanceToNowStrict } from "date-fns";
import { ApiError } from "@/lib/api";
import type { ListResponse, Validation, ValidationIssue } from "./types";

export function toItems<T>(data: ListResponse<T> | undefined | null): T[] {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  return Array.isArray(data.items) ? data.items : [];
}

export function errorStatus(e: unknown): number | undefined {
  return e instanceof ApiError ? e.status : undefined;
}

/** 404/405/501 → the backend module is not there yet; UIs render a calm "not available yet" state. */
export function isNotAvailable(e: unknown): boolean {
  const s = errorStatus(e);
  return s === 404 || s === 405 || s === 501;
}

export function errorMessage(e: unknown, fallback = "Something went wrong"): string {
  if (e instanceof ApiError) return e.problem.detail || e.problem.title || fallback;
  if (e instanceof Error) return e.message || fallback;
  return fallback;
}

export function problemCode(e: unknown): string | undefined {
  if (!(e instanceof ApiError)) return undefined;
  const first = e.problem.errors?.find((x) => x.code)?.code;
  return e.code !== "error" ? e.code : first;
}

export function requestId(e: unknown): string | undefined {
  if (!(e instanceof ApiError)) return undefined;
  return e.problem.instance || undefined;
}

/** Map Problem Details `errors[]` to `{field: message}`; field-less errors land under `_`. */
export function fieldErrors(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError)) return {};
  const out: Record<string, string> = {};
  for (const raw of e.problem.errors ?? []) {
    const err = raw as { code?: string; field?: string; message?: string; node_key?: string; loc?: (string | number)[] };
    const key = err.field ?? err.node_key ?? (Array.isArray(err.loc) ? String(err.loc[err.loc.length - 1]) : undefined) ?? "_";
    const msg = err.message ?? err.code ?? "Invalid value";
    out[key] = out[key] ? `${out[key]} · ${msg}` : msg;
  }
  return out;
}

export function validationIssues(v: Validation | null | undefined): { errors: ValidationIssue[]; warnings: ValidationIssue[] } {
  if (!v) return { errors: [], warnings: [] };
  const errors = [...(v.errors ?? [])];
  const warnings = [...(v.warnings ?? [])];
  for (const i of v.issues ?? []) {
    if (i.severity === "warning" || i.severity === "info") warnings.push(i);
    else errors.push(i);
  }
  return { errors, warnings };
}

const nf = new Intl.NumberFormat("en-US");
const cf = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

export function fmtInt(n: number | null | undefined): string {
  return n == null || Number.isNaN(Number(n)) ? "n/a" : nf.format(Number(n));
}
export function fmtCompact(n: number | null | undefined): string {
  return n == null || Number.isNaN(Number(n)) ? "n/a" : cf.format(Number(n));
}
/** Rates may arrive as fractions (0.046) or percents (4.6); values ≤ 1 are treated as fractions. */
export function toPercent(v: number | null | undefined): number | null {
  if (v == null || Number.isNaN(Number(v))) return null;
  const n = Number(v);
  return Math.abs(n) <= 1 ? n * 100 : n;
}
export function fmtPct(v: number | null | undefined, digits = 1): string {
  const p = toPercent(v);
  return p == null ? "n/a" : `${p.toFixed(digits)}%`;
}
export function fmtUsd(v: number | null | undefined): string {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  return `$${n.toFixed(n !== 0 && Math.abs(n) < 0.1 ? 3 : 2)}`;
}
export function relTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return formatDistanceToNowStrict(d, { addSuffix: true });
}
export function fmtDateTime(iso: string | null | undefined, tz?: string, opts?: Intl.DateTimeFormatOptions): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return new Intl.DateTimeFormat("en-US", { timeZone: tz, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", ...opts }).format(d);
}
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" }).format(d);
}
export function truncate(s: string | null | undefined, n: number): string {
  if (!s) return "";
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

/** Trigger a browser download for an authenticated GET (cookies + bearer + workspace header). */
export async function downloadAuthed(path: string, filename: string, headers: Record<string, string>): Promise<void> {
  const res = await fetch(`/api/v1${path}`, { headers, credentials: "include" });
  if (!res.ok) {
    let detail = res.statusText;
    try { const p = (await res.json()) as { detail?: string; title?: string }; detail = p.detail || p.title || detail; } catch { /* not json */ }
    throw new ApiError({ type: res.status === 501 ? "not_implemented" : "http_error", title: detail, status: res.status, detail });
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadText(content: string, filename: string, mime = "text/csv;charset=utf-8"): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function toCsv(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return "";
  const cols = Array.from(rows.reduce((s, r) => { Object.keys(r).forEach((k) => s.add(k)); return s; }, new Set<string>()));
  const esc = (v: unknown) => {
    if (v == null) return "";
    const s = typeof v === "object" ? JSON.stringify(v) : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}
export function num(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
export function str(v: unknown): string | null {
  return typeof v === "string" ? v : v == null ? null : String(v);
}
