"use client";
import { useState } from "react";
import Link from "next/link";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ListSkeleton, QueryError } from "@/components/shared/async-states";
import { fmtRelative, fmtUsd, truncate } from "@/lib/formatters";
import { cn } from "@/lib/utils";
import { useSession } from "@/stores/session";
import { useRuns } from "../hooks";
import { runTitle } from "../types";
import { TaskGlyph } from "./task-glyph";

const STATUSES = ["all", "running", "awaiting_approval", "completed", "failed", "cancelled"];

export function RunHistory({ activeId, onNavigate }: { activeId?: string; onNavigate?: () => void }) {
  const slug = useSession((s) => s.workspaceSlug);
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const runs = useRuns(status === "all" ? {} : { status });
  const list = (runs.data ?? []).filter((r) => !search || runTitle(r).toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Runs</h2>
        <Button asChild size="xs" variant="outline"><Link href={`/w/${slug}/command-center`} onClick={onNavigate}><Plus className="h-3 w-3" /> New run</Link></Button>
      </div>
      <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search runs…" className="h-8" aria-label="Search runs" />
      <Select value={status} onValueChange={setStatus}>
        <SelectTrigger size="sm" className="w-full" aria-label="Filter by status"><SelectValue /></SelectTrigger>
        <SelectContent>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s === "all" ? "All statuses" : s.replace(/_/g, " ")}</SelectItem>)}</SelectContent>
      </Select>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {runs.isLoading ? <ListSkeleton rows={6} rowClassName="h-10" /> : runs.error ? (
          <QueryError error={runs.error} onRetry={() => runs.refetch()} title="Couldn't load runs" />
        ) : !list.length ? (
          <p className="p-3 text-center text-xs text-muted-foreground">{search || status !== "all" ? "No runs match." : "No runs yet."}</p>
        ) : (
          <ul className="space-y-0.5">
            {list.map((r) => (
              <li key={r.id}>
                <Link href={`/w/${slug}/command-center/${r.id}`} onClick={onNavigate}
                      className={cn("flex items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent", r.id === activeId && "bg-accent font-medium")}
                      aria-current={r.id === activeId ? "page" : undefined}>
                  <TaskGlyph status={r.status === "completed" ? "succeeded" : r.status} className="mt-0.5" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{truncate(runTitle(r), 60)}</span>
                    <span className="block text-xs font-normal text-muted-foreground">{fmtRelative(r.created_at ?? r.queued_at)} · {fmtUsd(r.cost_usd)}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
