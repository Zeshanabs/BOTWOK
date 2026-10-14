import { cn } from "@/lib/utils";
import { STATUS_STYLES, statusLabel } from "@/lib/status";

export function StatusChip({ status, className }: { status: string; className?: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", STATUS_STYLES[status] ?? "bg-gray-100 text-gray-700", className)}>
      {statusLabel(status)}
    </span>
  );
}
