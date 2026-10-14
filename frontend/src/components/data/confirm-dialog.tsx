"use client";
/** Destructive confirm naming the object and consequence; optional typed confirmation (doc 24 §0.6). */
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = "Confirm", destructive = true, typeToConfirm, busy, onConfirm, children }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  /** When set, the user must type this exact text before confirming. */
  typeToConfirm?: string;
  busy?: boolean;
  onConfirm: () => void;
  children?: React.ReactNode;
}) {
  const [typed, setTyped] = useState("");
  const blocked = !!typeToConfirm && typed.trim() !== typeToConfirm;
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) setTyped(""); onOpenChange(o); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription asChild><div>{description}</div></DialogDescription>}
        </DialogHeader>
        {children}
        {typeToConfirm && (
          <div className="space-y-1">
            <Label htmlFor="confirm-typed">Type <span className="font-mono font-semibold">{typeToConfirm}</span> to confirm</Label>
            <Input id="confirm-typed" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant={destructive ? "destructive" : "default"} disabled={blocked || busy} onClick={onConfirm}>
            {busy ? "Working…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
