"use client";
import { useState } from "react";
import { Bookmark, Globe, Heart, MessageCircle, MoreHorizontal, Repeat2, Send, Share2, ThumbsUp } from "lucide-react";
import { PlatformIcon } from "@/components/shared/platform-icon";
import { platformMeta } from "@/lib/platforms";
import { cn } from "@/lib/utils";
import { MediaThumb } from "@/features/media/components/media-thumb";
import { composeVariant, countText, ruleFor } from "../platform-rules";

export interface PreviewMedia { id: string; kind?: string; mime?: string; url?: string | null; thumbnail_url?: string | null; alt_text?: string | null }

const TOKEN_RE = /(https?:\/\/[^\s]+|#[\p{L}\p{N}_]+|@[\w.]+)/gu;

/** Render text with hashtags, mentions and links styled like the platform. */
export function RichPostText({ text, accent }: { text: string; accent: string }) {
  const parts = text.split(TOKEN_RE);
  return (
    <>
      {parts.map((p, i) => (i % 2 === 1
        ? <span key={i} style={{ color: accent }} className="font-medium">{p.startsWith("http") ? p.replace(/^https?:\/\//, "").slice(0, 28) + (p.length > 36 ? "…" : "") : p}</span>
        : <span key={i}>{p}</span>))}
    </>
  );
}

function Folded({ text, foldAt, accent, moreLabel }: { text: string; foldAt?: number; accent: string; moreLabel: string }) {
  const [open, setOpen] = useState(false);
  const chars = Array.from(text);
  if (!foldAt || open || chars.length <= foldAt) return <p className="whitespace-pre-wrap break-words"><RichPostText text={text} accent={accent} /></p>;
  const cut = chars.slice(0, foldAt).join("").replace(/\s+\S*$/, "");
  return (
    <p className="whitespace-pre-wrap break-words">
      <RichPostText text={cut} accent={accent} />
      <button type="button" className="ml-1 text-muted-foreground hover:underline" onClick={() => setOpen(true)}>{moreLabel}</button>
    </p>
  );
}

function MediaBlock({ media, aspect, max = 4, carousel }: { media: PreviewMedia[]; aspect: string; max?: number; carousel?: boolean }) {
  if (!media.length) return null;
  if (carousel || media.length === 1) {
    return (
      <Frame media={media[0]} aspect={aspect}>
        {media.length > 1 && (
          <div className="absolute bottom-2 left-1/2 flex -translate-x-1/2 gap-1" aria-label={`${media.length} slides`}>
            {media.slice(0, 10).map((m, i) => <span key={m.id} className={cn("h-1.5 w-1.5 rounded-full", i === 0 ? "bg-white" : "bg-white/50")} />)}
          </div>
        )}
      </Frame>
    );
  }
  const shown = media.slice(0, max);
  return (
    <div className={cn("grid grid-cols-2 gap-0.5", shown.length > 2 ? "grid-rows-2" : "grid-rows-1")} style={{ aspectRatio: aspect }}>
      {shown.map((m, i) => (
        <div key={m.id} className={cn("relative", shown.length === 3 && i === 0 && "row-span-2")}>
          <MediaThumb asset={m} rounded={false} className="absolute inset-0 h-full w-full" />
        </div>
      ))}
    </div>
  );
}

/** Aspect-correct media frame (MediaThumb fills an aspect box). */
function Frame({ media, aspect, className, children }: { media?: PreviewMedia; aspect: string; className?: string; children?: React.ReactNode }) {
  return (
    <div className={cn("relative w-full overflow-hidden bg-muted", className)} style={{ aspectRatio: aspect }}>
      {media ? <MediaThumb asset={media} rounded={false} className="absolute inset-0 h-full w-full" /> : <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground">No media attached</div>}
      {children}
    </div>
  );
}

function Avatar({ name, color }: { name: string; color: string }) {
  return <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white" style={{ background: color }}>{name.slice(0, 2).toUpperCase()}</span>;
}

/**
 * Approximate, platform-accurate-enough preview (doc 23 §23.4): truncation and "see more" folds, hashtag/link styling,
 * thread splitting for X/Threads, media aspect per platform, over-limit text highlighted.
 */
export function PlatformPreview({ platform, text, hashtags, segments, media = [], authorName = "Your brand", handle = "yourbrand", title, format, className }: {
  platform: string; text: string; hashtags?: string[]; segments?: string[]; media?: PreviewMedia[]; authorName?: string; handle?: string;
  title?: string | null; format?: string; className?: string;
}) {
  const meta = platformMeta(platform);
  const rule = ruleFor(platform);
  const full = composeVariant(text, hashtags);
  const accent = platform === "x" || platform === "threads" ? "#1d9bf0" : platform === "instagram" ? "#00376b" : platform === "tiktok" ? "#fe2c55" : meta.color;
  const shell = "rounded-xl border bg-card text-card-foreground text-[13px] leading-relaxed shadow-xs";
  const over = rule ? countText(full, rule.mode) > rule.textLimit && !(segments && segments.length) : false;
  const overNote = over && rule ? <p className="mt-2 rounded bg-red-50 px-2 py-1 text-xs text-red-700 dark:bg-red-900/30 dark:text-red-200">Over the {rule.textLimit.toLocaleString()} {rule.mode === "utf8_bytes" ? "byte" : "character"} limit — the platform will reject or truncate this.</p> : null;
  const label = <p className="mb-2 flex items-center gap-1.5 text-xs text-muted-foreground"><PlatformIcon platform={platform} size={14} /> Approximate {meta.label} preview{format ? ` · ${format.replace(/_/g, " ")}` : ""}</p>;

  if (platform === "x" || platform === "threads") {
    const posts = segments && segments.length ? segments : [full];
    return (
      <div className={className}>{label}
        <div className={cn(shell, "p-3")}>
          {posts.map((p, i) => (
            <div key={i} className="relative flex gap-3 pb-3 last:pb-0">
              {i < posts.length - 1 && <span className="absolute left-[18px] top-10 bottom-0 w-px bg-border" aria-hidden />}
              <Avatar name={authorName} color={meta.color} />
              <div className="min-w-0 flex-1">
                <p className="text-sm"><span className="font-semibold">{authorName}</span> <span className="text-muted-foreground">@{handle} · now</span></p>
                <p className={cn("whitespace-pre-wrap break-words", rule && countText(p, rule.mode) > rule.textLimit && "rounded bg-red-50 dark:bg-red-900/30")}><RichPostText text={p} accent={accent} /></p>
                {i === 0 && media.length > 0 && <div className="mt-2 overflow-hidden rounded-xl border"><MediaBlock media={media} aspect="16 / 9" max={platform === "x" ? 4 : 20} /></div>}
                <div className="mt-2 flex justify-between pr-8 text-muted-foreground" aria-hidden>
                  <MessageCircle className="h-4 w-4" /><Repeat2 className="h-4 w-4" /><Heart className="h-4 w-4" /><Share2 className="h-4 w-4" />
                </div>
              </div>
            </div>
          ))}
        </div>
        {overNote}
      </div>
    );
  }

  if (platform === "instagram" || platform === "tiktok") {
    const isTT = platform === "tiktok" || format === "short_video" || format === "story";
    if (isTT) {
      return (
        <div className={className}>{label}
          <div className="mx-auto max-w-[260px]">
            <Frame media={media[0]} aspect="9 / 16" className="rounded-xl">
              <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-3 text-xs text-white">
                <p className="font-semibold">@{handle}</p>
                <p className="line-clamp-3 whitespace-pre-wrap"><RichPostText text={full} accent="#ffffff" /></p>
              </div>
            </Frame>
          </div>
          {overNote}
        </div>
      );
    }
    return (
      <div className={className}>{label}
        <div className={cn(shell, "overflow-hidden")}>
          <div className="flex items-center gap-2 p-2.5"><Avatar name={authorName} color={meta.color} /><span className="text-sm font-semibold">{handle}</span><MoreHorizontal className="ml-auto h-4 w-4" aria-hidden /></div>
          <Frame media={media[0]} aspect={format === "carousel" || media.length > 1 ? "4 / 5" : "4 / 5"}>
            {media.length > 1 && <span className="absolute right-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[11px] text-white">1/{media.length}</span>}
          </Frame>
          <div className="flex items-center gap-3 p-2.5" aria-hidden><Heart className="h-5 w-5" /><MessageCircle className="h-5 w-5" /><Send className="h-5 w-5" /><Bookmark className="ml-auto h-5 w-5" /></div>
          <div className="px-2.5 pb-3"><Folded text={`${handle} ${full}`} foldAt={125} accent={accent} moreLabel="… more" /></div>
        </div>
        {!media.length && <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">Instagram requires at least one image or video.</p>}
        {overNote}
      </div>
    );
  }

  if (platform === "youtube") {
    return (
      <div className={className}>{label}
        <div className={cn(shell, "overflow-hidden")}>
          <Frame media={media[0]} aspect={format === "short_video" ? "9 / 16" : "16 / 9"} className={format === "short_video" ? "mx-auto max-w-[240px]" : undefined} />
          <div className="space-y-1 p-3">
            <p className={cn("text-sm font-semibold", (title ?? "").length > 100 && "text-red-600")}>{title || <span className="text-muted-foreground">Add a video title</span>}</p>
            <div className="rounded-lg bg-muted p-2 text-xs"><Folded text={full} foldAt={160} accent="#065fd4" moreLabel="…more" /></div>
          </div>
        </div>
        {overNote}
      </div>
    );
  }

  if (platform === "pinterest") {
    return (
      <div className={className}>{label}
        <div className="mx-auto max-w-[260px] space-y-2">
          <Frame media={media[0]} aspect="2 / 3" className="rounded-2xl" />
          <p className="text-sm font-semibold">{title || <span className="text-muted-foreground">Add a pin title</span>}</p>
          <p className="line-clamp-3 text-xs text-muted-foreground"><RichPostText text={full} accent={accent} /></p>
        </div>
        {overNote}
      </div>
    );
  }

  if (platform === "gbp") {
    return (
      <div className={className}>{label}
        <div className={cn(shell, "overflow-hidden")}>
          {media[0] && <Frame media={media[0]} aspect="4 / 3" />}
          <div className="space-y-2 p-3">
            <p className="text-sm font-semibold">{authorName}</p>
            <Folded text={full} foldAt={300} accent={accent} moreLabel="More" />
            <span className="inline-block rounded-md border px-3 py-1 text-xs font-medium" style={{ color: accent }}>Learn more</span>
          </div>
        </div>
        {overNote}
      </div>
    );
  }

  // linkedin + facebook
  const isLi = platform === "linkedin";
  return (
    <div className={className}>{label}
      <div className={cn(shell, "overflow-hidden")}>
        <div className="flex gap-2 p-3">
          <Avatar name={authorName} color={meta.color} />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold">{authorName}</p>
            <p className="flex items-center gap-1 text-xs text-muted-foreground">{isLi ? "1,204 followers · Now" : "Just now"} · <Globe className="h-3 w-3" aria-hidden /></p>
          </div>
          <MoreHorizontal className="h-4 w-4 text-muted-foreground" aria-hidden />
        </div>
        <div className="px-3 pb-2"><Folded text={full} foldAt={rule?.foldAt} accent={accent} moreLabel={isLi ? "…see more" : "See more"} /></div>
        {media.length > 0 && <MediaBlock media={media} aspect={media.length === 1 ? (format === "document" ? "4 / 5" : "1.91 / 1") : "1 / 1"} max={4} carousel={format === "document"} />}
        <div className="flex justify-around border-t px-2 py-2 text-xs text-muted-foreground" aria-hidden>
          <span className="flex items-center gap-1"><ThumbsUp className="h-4 w-4" /> Like</span>
          <span className="flex items-center gap-1"><MessageCircle className="h-4 w-4" /> Comment</span>
          <span className="flex items-center gap-1"><Repeat2 className="h-4 w-4" /> Repost</span>
          <span className="flex items-center gap-1"><Send className="h-4 w-4" /> Send</span>
        </div>
      </div>
      {overNote}
    </div>
  );
}
