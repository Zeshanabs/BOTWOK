"use client";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { StatusChip } from "@/components/shared/status-chip";
import { usePermissions } from "@/features/common/hooks";
import type { ContentStatus } from "@/features/common/types";

type Need = "create" | "approve" | "manage";
interface T { to: ContentStatus; label: string; need: Need }
const ARCHIVE: T = { to: "archived", label: "Archive", need: "manage" };
/** Guard matrix from doc 17 (transition): draft→needs_review (editor), needs_review→approved|rejected (approver), *→archived (admin), approved→draft (editor). */
export const TRANSITIONS: Record<ContentStatus, T[]> = {
  idea: [{ to: "draft", label: "Move to draft", need: "create" }, ARCHIVE],
  draft: [{ to: "needs_review", label: "Send to review", need: "create" }, ARCHIVE],
  ai_generated: [{ to: "needs_review", label: "Send to review", need: "create" }, { to: "draft", label: "Back to draft", need: "create" }, ARCHIVE],
  needs_review: [{ to: "approved", label: "Approve", need: "approve" }, { to: "rejected", label: "Reject", need: "approve" }, { to: "draft", label: "Withdraw to draft", need: "create" }, ARCHIVE],
  approved: [{ to: "draft", label: "Reopen as draft (unschedules)", need: "create" }, ARCHIVE],
  rejected: [{ to: "draft", label: "Revise as draft", need: "create" }, ARCHIVE],
  archived: [{ to: "draft", label: "Restore to draft", need: "manage" }],
};

export function useAllowedTransitions(status: ContentStatus) {
  const p = usePermissions();
  return (TRANSITIONS[status] ?? []).filter((t) => (t.need === "create" ? p.canCreate : t.need === "approve" ? p.canApprove : p.canManage));
}

/** Status badge menu offering only valid, role-permitted transitions. */
export function StatusMenu({ status, onTransition, pending }: { status: ContentStatus; onTransition: (to: ContentStatus) => void; pending?: boolean }) {
  const allowed = useAllowedTransitions(status);
  if (!allowed.length) return <StatusChip status={status} />;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 gap-1 px-1" disabled={pending} aria-label={`Status: ${status}. Change status`}>
          <StatusChip status={status} /><ChevronDown className="h-3 w-3" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        <DropdownMenuLabel>Move to</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {allowed.map((t) => <DropdownMenuItem key={t.to + t.label} onClick={() => onTransition(t.to)}><StatusChip status={t.to} className="mr-2" />{t.label}</DropdownMenuItem>)}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
