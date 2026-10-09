"use client";
import { useState } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Destructive confirm naming the object and the exact consequence; optional typed confirmation (doc 24 §0.6). */
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = "Confirm", destructive = true, typeToConfirm, busy, onConfirm, children }: {
  open: boolean; onOpenChange: (open: boolean) => void; title: string; description: React.ReactNode; confirmLabel?: string;
  destructive?: boolean; typeToConfirm?: string; busy?: boolean; onConfirm: () => unknown; children?: React.ReactNode;
}) {
  const [typed, setTyped] = useState("");
  const blocked = !!typeToConfirm && typed.trim() !== typeToConfirm;
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) setTyped(""); onOpenChange(o); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader className="sm:flex-row sm:gap-4">
          {destructive && (
            <div className="mx-auto flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-destructive/10 text-destructive sm:mx-0" aria-hidden>
              <AlertTriangle className="h-5 w-5" />
            </div>
          )}
          <div className="min-w-0 space-y-1.5">
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription asChild><div className="space-y-2 text-sm text-muted-foreground">{description}</div></DialogDescription>
          </div>
        </DialogHeader>
        {children}
        {typeToConfirm && (
          <div className="space-y-1.5">
            <Label htmlFor="confirm-type">Type <span className="font-mono font-semibold text-foreground">{typeToConfirm}</span> to confirm</Label>
            <Input id="confirm-type" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" autoFocus />
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button variant={destructive ? "destructive" : "default"} disabled={blocked || busy} onClick={() => void onConfirm()}>
            {busy && <Loader2 className="animate-spin" />} {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
