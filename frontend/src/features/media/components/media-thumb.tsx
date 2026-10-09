"use client";
import Image from "next/image";
import { AlertTriangle, FileText, Film, ImageIcon, Loader2, Music } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMediaUrl } from "../hooks";

interface ThumbAsset { id: string; kind?: string; mime?: string; url?: string | null; thumbnail_url?: string | null; alt_text?: string | null; status?: string; error?: string | null }

/** Thumbnail for an asset; resolves a presigned URL via GET /media/{id}/url when the list didn't include one. */
export function MediaThumb({ asset, className, fit = "cover", rounded = true }: { asset: ThumbAsset; className?: string; fit?: "cover" | "contain"; rounded?: boolean }) {
  const known = asset.thumbnail_url ?? asset.url ?? null;
  const q = useMediaUrl(asset.id, known);
  const src = known ?? q.data?.thumbnail_url ?? q.data?.url ?? null;
  const kind = asset.kind ?? (asset.mime?.split("/")[0] || "image");
  const base = cn("relative flex items-center justify-center overflow-hidden bg-muted", rounded && "rounded-md", className);
  if (asset.status === "processing") return <div className={base}><Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-label="Processing" /></div>;
  if (asset.status === "failed") return <div className={base} title={asset.error ?? "Processing failed"}><AlertTriangle className="h-5 w-5 text-destructive" aria-label="Failed" /></div>;
  if (kind === "image" && src) {
    return (
      <div className={base}>
        <Image src={src} alt={asset.alt_text ?? ""} fill unoptimized sizes="320px" className={fit === "cover" ? "object-cover" : "object-contain"} />
      </div>
    );
  }
  if (kind === "video" && src) {
    return <div className={base}><video src={src} muted preload="metadata" className={cn("h-full w-full", fit === "cover" ? "object-cover" : "object-contain")} aria-label={asset.alt_text ?? "Video"} /></div>;
  }
  const Icon = kind === "video" ? Film : kind === "audio" ? Music : kind === "document" ? FileText : ImageIcon;
  return <div className={base}>{q.isLoading ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : <Icon className="h-6 w-6 text-muted-foreground" aria-hidden />}</div>;
}
