"use client";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { errorMessage } from "@/features/common/utils";
import { mediaApi, type MediaAsset, type MediaFilters } from "./api";

export const mediaKeys = {
  list: (f: MediaFilters) => ["media", "list", f] as const,
  detail: (id: string) => ["media", id] as const,
  url: (id: string) => ["media", id, "url"] as const,
};

export function useMediaList(f: MediaFilters, enabled = true) {
  return useQuery({ queryKey: mediaKeys.list(f), queryFn: () => mediaApi.list(f), enabled });
}
export function useMediaAsset(id: string | null) {
  return useQuery({ queryKey: mediaKeys.detail(id ?? ""), queryFn: () => mediaApi.get(id as string), enabled: !!id });
}
/** Presigned GET URL for an asset (cached ~10 min). */
export function useMediaUrl(id: string | null | undefined, known?: string | null) {
  return useQuery({
    queryKey: mediaKeys.url(id ?? ""),
    queryFn: () => mediaApi.url(id as string),
    enabled: !!id && !known,
    staleTime: 9 * 60_000,
    retry: false,
  });
}

export interface UploadProgress { name: string; status: "uploading" | "registering" | "done" | "failed"; error?: string }

/** Presigned upload: POST /media/upload-url → PUT (or form POST) → POST /media. */
export function useUpload(brandId: string | null | undefined) {
  const qc = useQueryClient();
  const [progress, setProgress] = useState<UploadProgress[]>([]);
  const mutation = useMutation({
    mutationFn: async (files: File[]): Promise<MediaAsset[]> => {
      setProgress(files.map((f) => ({ name: f.name, status: "uploading" })));
      const out: MediaAsset[] = [];
      for (const [i, file] of files.entries()) {
        const set = (p: Partial<UploadProgress>) => setProgress((cur) => cur.map((x, j) => (j === i ? { ...x, ...p } : x)));
        try {
          const mime = file.type || "application/octet-stream";
          const ticket = await mediaApi.uploadUrl({ filename: file.name, content_type: mime, size_bytes: file.size });
          const key = ticket.key ?? ticket.object_key;
          if (!key) throw new Error("Upload ticket has no object key");
          let res: Response;
          if (ticket.fields && (ticket.method ?? "POST") === "POST") {
            const fd = new FormData();
            Object.entries(ticket.fields).forEach(([k, v]) => fd.append(k, v));
            fd.append("file", file);
            res = await fetch(ticket.upload_url, { method: "POST", body: fd });
          } else {
            res = await fetch(ticket.upload_url, { method: "PUT", body: file, headers: { "Content-Type": mime, ...(ticket.headers ?? {}) } });
          }
          if (!res.ok) throw new Error(`Storage rejected the upload (${res.status})`);
          set({ status: "registering" });
          const asset = await mediaApi.create({ key, filename: file.name, brand_id: brandId });
          out.push(asset);
          set({ status: "done" });
        } catch (e) {
          set({ status: "failed", error: errorMessage(e) });
          toast.error(`${file.name}: ${errorMessage(e)}`);
        }
      }
      return out;
    },
    onSuccess: (assets) => { if (assets.length) toast.success(`Uploaded ${assets.length} file${assets.length === 1 ? "" : "s"}`); },
    onSettled: () => { void qc.invalidateQueries({ queryKey: ["media"] }); },
  });
  return { upload: mutation.mutateAsync, isUploading: mutation.isPending, progress, clear: () => setProgress([]) };
}
