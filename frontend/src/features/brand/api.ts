import { api } from "@/lib/api";
import type { Page } from "@/lib/formatters";
import type { Brand, BrandContext, BrandCreateInput, BrandSettings, BrandSettingsUpdate, Pillar, PillarInput } from "./types";

export const brandApi = {
  list: () => api.get<Page<Brand> | Brand[]>("/brands"),
  get: (id: string) => api.get<Brand>(`/brands/${id}`),
  create: (body: BrandCreateInput) => api.post<Brand>("/brands", body),
  update: (id: string, body: Partial<BrandCreateInput> & { logo_asset_id?: string | null; languages?: string[] }) => api.patch<Brand>(`/brands/${id}`, body),
  settings: (id: string) => api.get<BrandSettings>(`/brands/${id}/settings`),
  putSettings: (id: string, body: BrandSettingsUpdate) => api.put<BrandSettings>(`/brands/${id}/settings`, body),
  pillars: (id: string) => api.get<Page<Pillar> | Pillar[]>(`/brands/${id}/pillars`),
  createPillar: (id: string, body: PillarInput) => api.post<Pillar>(`/brands/${id}/pillars`, body),
  updatePillar: (id: string, pillarId: string, body: PillarInput) => api.patch<Pillar>(`/brands/${id}/pillars/${pillarId}`, body),
  deletePillar: (id: string, pillarId: string) => api.delete<unknown>(`/brands/${id}/pillars/${pillarId}`),
  context: (id: string) => api.get<BrandContext>(`/brands/${id}/context`),
  importFromWebsite: (id: string, url: string) => api.post<{ run_id: string; status_url?: string }>(`/brands/${id}/import-from-website`, { url }),
  addAsset: (id: string, body: { kind: string; media_asset_id: string; meta?: Record<string, unknown> }) => api.post<{ id: string }>(`/brands/${id}/assets`, body),
};

interface UploadUrlResponse { upload_url?: string; url?: string; object_key?: string; key?: string; headers?: Record<string, string>; media_id?: string; id?: string }
interface MediaAssetResponse { id: string }

/**
 * Upload flow (doc 25 B1.3): presigned PUT to object storage, then register the media asset, then attach it to the brand.
 * Returns the brand asset id (or media id when the server does not return one).
 */
export async function uploadBrandAsset(brandId: string, file: File, kind: "logo" | "logo_dark" | "reference_image" = "logo"): Promise<{ mediaId: string; assetId: string }> {
  const meta = { filename: file.name, content_type: file.type, mime: file.type, size: file.size, bytes: file.size, brand_id: brandId, kind: "image" };
  const presigned = await api.post<UploadUrlResponse>("/media/upload-url", meta);
  const uploadUrl = presigned.upload_url ?? presigned.url;
  const objectKey = presigned.object_key ?? presigned.key;
  if (!uploadUrl) throw new Error("The server did not return an upload URL");
  const put = await fetch(uploadUrl, { method: "PUT", body: file, headers: { "Content-Type": file.type, ...(presigned.headers ?? {}) } });
  if (!put.ok) throw new Error(`Upload failed (${put.status})`);
  let mediaId = presigned.media_id ?? presigned.id;
  if (!mediaId || objectKey) {
    const media = await api.post<MediaAssetResponse>("/media", { ...meta, object_key: objectKey, source: "upload", origin: "uploaded" });
    mediaId = media.id;
  }
  const asset = await brandApi.addAsset(brandId, { kind, media_asset_id: mediaId, meta: { filename: file.name } });
  return { mediaId, assetId: asset?.id ?? mediaId };
}
