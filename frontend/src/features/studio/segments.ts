/** Normalized view of content_variants.segments (thread posts, carousel slides, script scenes). */
export interface Seg { text: string; media_asset_id?: string | null; title?: string | null; rest: Record<string, unknown> }

export function toSegs(raw: unknown[] | undefined | null): { segs: Seg[]; stringMode: boolean } {
  const arr = Array.isArray(raw) ? raw : [];
  const stringMode = arr.length === 0 || arr.every((x) => typeof x === "string");
  const segs = arr.map((x): Seg => {
    if (typeof x === "string") return { text: x, rest: {} };
    if (x && typeof x === "object") {
      const o = x as Record<string, unknown>;
      const { text, body, media_asset_id, title, ...rest } = o;
      return { text: typeof text === "string" ? text : typeof body === "string" ? body : "", media_asset_id: typeof media_asset_id === "string" ? media_asset_id : null, title: typeof title === "string" ? title : null, rest };
    }
    return { text: String(x ?? ""), rest: {} };
  });
  return { segs, stringMode };
}

export function fromSegs(segs: Seg[], stringMode: boolean): unknown[] {
  if (stringMode && segs.every((s) => !s.media_asset_id && !s.title && Object.keys(s.rest).length === 0)) return segs.map((s) => s.text);
  return segs.map((s) => ({ ...s.rest, text: s.text, ...(s.title ? { title: s.title } : {}), ...(s.media_asset_id ? { media_asset_id: s.media_asset_id } : {}) }));
}

export function segsEqual(a: Seg[], b: Seg[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((s, i) => s.text === b[i].text && (s.media_asset_id ?? null) === (b[i].media_asset_id ?? null) && (s.title ?? null) === (b[i].title ?? null));
}
