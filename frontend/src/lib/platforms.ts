export type Platform = "facebook" | "instagram" | "threads" | "linkedin" | "x" | "tiktok" | "youtube" | "pinterest" | "gbp";
export const PLATFORMS: { id: Platform; label: string; color: string; short: string }[] = [
  { id: "linkedin", label: "LinkedIn", color: "#0A66C2", short: "in" },
  { id: "x", label: "X", color: "#000000", short: "X" },
  { id: "instagram", label: "Instagram", color: "#E1306C", short: "IG" },
  { id: "facebook", label: "Facebook", color: "#1877F2", short: "FB" },
  { id: "threads", label: "Threads", color: "#000000", short: "TH" },
  { id: "youtube", label: "YouTube", color: "#FF0000", short: "YT" },
  { id: "tiktok", label: "TikTok", color: "#000000", short: "TT" },
  { id: "pinterest", label: "Pinterest", color: "#E60023", short: "P" },
  { id: "gbp", label: "Google Business", color: "#4285F4", short: "G" },
];
export const platformMeta = (id: string) => PLATFORMS.find((p) => p.id === id) ?? { id: id as Platform, label: id, color: "#888", short: id.slice(0, 2).toUpperCase() };
