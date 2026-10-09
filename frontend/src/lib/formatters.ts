/** Small, dependency-light formatting helpers shared by feature screens. */
import { format, formatDistanceToNowStrict, isValid, parseISO } from "date-fns";

export interface Page<T> {
  items: T[];
  next_cursor?: string | null;
  total?: number;
}

/** Normalizes list responses that may be `{items}` envelopes or plain arrays. */
export function toItems<T>(data: Page<T> | T[] | null | undefined): T[] {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  return Array.isArray(data.items) ? data.items : [];
}

export function toNumber(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export function fmtUsd(v: unknown, digits = 3): string {
  const n = toNumber(v);
  if (n === null) return "—";
  if (n !== 0 && Math.abs(n) < 0.001) return "<$0.001";
  return `$${n.toFixed(digits)}`;
}

export function fmtDuration(ms: unknown): string {
  const n = toNumber(ms);
  if (n === null) return "";
  if (n < 1000) return `${Math.round(n)}ms`;
  const s = n / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s % 60);
  if (m < 60) return `${m}m ${rest}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function fmtCompact(v: unknown): string {
  const n = toNumber(v);
  if (n === null) return "—";
  return new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function fmtPercent(v: unknown, digits = 0): string {
  const n = toNumber(v);
  if (n === null) return "—";
  return `${(n <= 1 && n >= -1 ? n * 100 : n).toFixed(digits)}%`;
}

function toDate(v: string | Date | null | undefined): Date | null {
  if (!v) return null;
  const d = v instanceof Date ? v : parseISO(v);
  return isValid(d) ? d : null;
}

export function fmtDate(v: string | Date | null | undefined, pattern = "MMM d, yyyy"): string {
  const d = toDate(v);
  return d ? format(d, pattern) : "—";
}

export function fmtDateTime(v: string | Date | null | undefined): string {
  return fmtDate(v, "MMM d, yyyy HH:mm");
}

export function fmtRelative(v: string | Date | null | undefined): string {
  const d = toDate(v);
  return d ? `${formatDistanceToNowStrict(d)} ${d.getTime() > Date.now() ? "from now" : "ago"}` : "—";
}

/** Milliseconds from `v` until now (negative when `v` is in the future). */
export function msSince(v: string | Date | null | undefined, now: number): number | null {
  const d = toDate(v);
  return d ? now - d.getTime() : null;
}

export function domainOf(url: string | null | undefined): string {
  if (!url) return "";
  try {
    return new URL(url.startsWith("http") ? url : `https://${url}`).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function faviconUrl(domain: string | null | undefined): string | null {
  return domain ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=32` : null;
}

/** Scores may come back as 0–1 or 0–100; returns 0–100. */
export function score100(v: unknown): number | null {
  const n = toNumber(v);
  if (n === null) return null;
  return Math.round(n <= 1 ? n * 100 : n);
}

export function truncate(s: string | null | undefined, n: number): string {
  if (!s) return "";
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}

export function humanize(s: string | null | undefined): string {
  if (!s) return "";
  return s.replace(/[_.]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
