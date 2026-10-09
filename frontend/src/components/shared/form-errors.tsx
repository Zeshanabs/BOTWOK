import { AlertCircle } from "lucide-react";
import { errorMessage, fieldErrors, isNotAvailable, requestId } from "@/features/common/utils";
import { cn } from "@/lib/utils";

/** Problem Details `errors[]` → `{ field: message }` (field-less errors are left to <FormError>). */
export function problemFieldErrors(e: unknown): Record<string, string> {
  const all = fieldErrors(e);
  const { _, ...fields } = all;
  void _;
  return fields;
}

/** Inline message under a field; renders nothing when the field is valid. */
export function FieldError({ errors, name, className }: { errors: Record<string, string>; name: string; className?: string }) {
  const msg = errors[name];
  if (!msg) return null;
  return <p id={`${name}-error`} role="alert" className={cn("mt-1 flex items-start gap-1 text-xs text-destructive", className)}><AlertCircle className="mt-px h-3 w-3 shrink-0" aria-hidden />{msg}</p>;
}

/** Form-level error banner (request id included when the API returned one); renders nothing for null. */
export function FormError({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  const rid = requestId(error);
  return (
    <div role="alert" className={cn("flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/[0.06] px-3 py-2 text-sm text-destructive", className)}>
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0">
        <p>{isNotAvailable(error) ? "This action isn't available on this install yet." : errorMessage(error)}</p>
        {rid && <p className="mt-0.5 font-mono text-[11px] opacity-70">ref {rid.slice(-12)}</p>}
      </div>
    </div>
  );
}
