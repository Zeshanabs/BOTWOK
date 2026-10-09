"use client";
import { useRef } from "react";
import { Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { MediaAsset } from "../api";
import { useUpload } from "../hooks";

export function UploadButton({ brandId, onUploaded, accept = "image/*,video/*", multiple = true, label = "Upload", variant = "outline", size = "sm" }: {
  brandId: string | null | undefined; onUploaded?: (assets: MediaAsset[]) => void; accept?: string; multiple?: boolean; label?: string;
  variant?: "outline" | "default" | "secondary" | "ghost"; size?: "sm" | "default" | "xs";
}) {
  const input = useRef<HTMLInputElement>(null);
  const { upload, isUploading, progress } = useUpload(brandId);
  const active = progress.find((p) => p.status === "uploading" || p.status === "registering");
  return (
    <>
      <input ref={input} type="file" accept={accept} multiple={multiple} className="sr-only" aria-label="Choose files to upload"
             onChange={async (e) => {
               const files = Array.from(e.target.files ?? []);
               e.target.value = "";
               if (!files.length) return;
               const assets = await upload(files);
               if (assets.length) onUploaded?.(assets);
             }} />
      <Button type="button" variant={variant} size={size} onClick={() => input.current?.click()} disabled={isUploading}>
        {isUploading ? <Loader2 className="animate-spin" /> : <Upload />}
        {isUploading && active ? `${active.status === "registering" ? "Processing" : "Uploading"} ${active.name.slice(0, 18)}…` : label}
      </Button>
    </>
  );
}
