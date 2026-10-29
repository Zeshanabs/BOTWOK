"use client";
import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** Destructive confirm naming the object and the exact consequence; optional typed confirmation (doc 24 §0.6). */
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = "Confirm", destructive, typeToConfirm, pending, onConfirm, children }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description: React.ReactNode; confirmLabel?: string;
  destructive?: boolean; typeToConfirm?: string; pending?: boolean; onConfirm: () => void; children?: React.ReactNode;
}) {
  const [typed, setTyped] = useState("");
  const blocked = !!typeToConfirm && typed.trim() !== typeToConfirm;
  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) setTyped(""); onOpenChange(o); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription asChild><div className="space-y-2 text-sm text-muted-foreground">{description}</div></DialogDescription>
        </DialogHeader>
        {children}
        {typeToConfirm && (
          <div className="space-y-1.5">
            <Label htmlFor="confirm-type">Type <span className="font-mono font-semibold">{typeToConfirm}</span> to confirm</Label>
            <Input id="confirm-type" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant={destructive ? "destructive" : "default"} disabled={blocked || pending} onClick={onConfirm}>
            {pending && <Loader2 className="animate-spin" />} {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
