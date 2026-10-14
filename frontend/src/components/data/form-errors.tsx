"use client";
/** Problem Details (RFC 9457) → form field errors. */
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { isNotAvailable } from "./async-states";

export type FieldErrors = Record<string, string>;

/** Maps `problem.errors[]` to `{field: message}`; strips `body.` prefixes and keeps the last path segment too. */
export function problemFieldErrors(error: unknown): FieldErrors {
  if (!(error instanceof ApiError)) return {};
  const out: FieldErrors = {};
  for (const e of error.problem.errors ?? []) {
    if (!e.field) continue;
    const field = e.field.replace(/^body[.]/, "");
    const msg = e.message || e.code || "Invalid value";
    out[field] = msg;
    const last = field.split(".").pop();
    if (last && !(last in out)) out[last] = msg;
  }
  return out;
}

/** General (non-field) error text for a form, or null. */
export function formErrorText(error: unknown): string | null {
  if (!error) return null;
  if (isNotAvailable(error)) return "This action isn't available yet on this install.";
  if (error instanceof ApiError) {
    const unfielded = (error.problem.errors ?? []).filter((e) => !e.field).map((e) => e.message).filter(Boolean);
    if (unfielded.length) return unfielded.join(" · ");
    return error.problem.detail || error.problem.title || "Request failed";
  }
  return error instanceof Error ? error.message : "Request failed";
}

export function FieldError({ errors, name, className }: { errors: FieldErrors; name: string; className?: string }) {
  const msg = errors[name];
  if (!msg) return null;
  return <p id={`${name}-error`} role="alert" className={cn("text-xs text-destructive", className)}>{msg}</p>;
}

export function FormError({ error, className }: { error: unknown; className?: string }) {
  const text = formErrorText(error);
  if (!text) return null;
  return <p role="alert" className={cn("rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive", className)}>{text}</p>;
}
