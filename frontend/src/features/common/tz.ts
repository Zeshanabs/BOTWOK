/** Timezone math without extra deps (Intl only). Day keys are "YYYY-MM-DD" in a given IANA zone. */

export interface TzParts { year: number; month: number; day: number; hour: number; minute: number; second: number; weekday: number }

const fmtCache = new Map<string, Intl.DateTimeFormat>();
function formatter(tz: string): Intl.DateTimeFormat {
  let f = fmtCache.get(tz);
  if (!f) {
    try {
      f = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", weekday: "short" });
    } catch {
      f = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", weekday: "short" });
    }
    fmtCache.set(tz, f);
  }
  return f;
}
const WD: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

export function tzParts(date: Date, tz: string): TzParts {
  const parts = formatter(tz).formatToParts(date);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "0";
  return { year: Number(get("year")), month: Number(get("month")), day: Number(get("day")), hour: Number(get("hour")) % 24, minute: Number(get("minute")), second: Number(get("second")), weekday: WD[get("weekday")] ?? 0 };
}

function offsetMs(date: Date, tz: string): number {
  const p = tzParts(date, tz);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return asUtc - (date.getTime() - date.getMilliseconds());
}

/** Wall-clock time in `tz` → UTC Date. Non-existent DST times shift forward; ambiguous ones take the first. */
export function zonedToUtc(year: number, month: number, day: number, hour: number, minute: number, tz: string): Date {
  const guess = Date.UTC(year, month - 1, day, hour, minute);
  const o1 = offsetMs(new Date(guess), tz);
  let ts = guess - o1;
  const o2 = offsetMs(new Date(ts), tz);
  if (o2 !== o1) ts = guess - o2;
  return new Date(ts);
}

const pad = (n: number) => String(n).padStart(2, "0");

export function dayKey(date: Date, tz: string): string {
  const p = tzParts(date, tz);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}`;
}
export function parseDayKey(key: string): { y: number; m: number; d: number } {
  const [y, m, d] = key.split("-").map(Number);
  return { y, m, d };
}
/** Pure calendar arithmetic on day keys (UTC based, independent of tz). */
export function addDays(key: string, n: number): string {
  const { y, m, d } = parseDayKey(key);
  const dt = new Date(Date.UTC(y, m - 1, d + n));
  return `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-${pad(dt.getUTCDate())}`;
}
export function addMonths(key: string, n: number): string {
  const { y, m } = parseDayKey(key);
  const dt = new Date(Date.UTC(y, m - 1 + n, 1));
  return `${dt.getUTCFullYear()}-${pad(dt.getUTCMonth() + 1)}-01`;
}
export function weekdayOf(key: string): number {
  const { y, m, d } = parseDayKey(key);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();
}
/** Monday-start week. */
export function startOfWeek(key: string): string {
  const wd = weekdayOf(key);
  return addDays(key, -((wd + 6) % 7));
}
export function startOfMonth(key: string): string {
  const { y, m } = parseDayKey(key);
  return `${y}-${pad(m)}-01`;
}
export function daysBetween(a: string, b: string): number {
  const pa = parseDayKey(a); const pb = parseDayKey(b);
  return Math.round((Date.UTC(pb.y, pb.m - 1, pb.d) - Date.UTC(pa.y, pa.m - 1, pa.d)) / 86_400_000);
}
export function keyLabel(key: string, opts: Intl.DateTimeFormatOptions): string {
  const { y, m, d } = parseDayKey(key);
  return new Intl.DateTimeFormat("en-US", { timeZone: "UTC", ...opts }).format(new Date(Date.UTC(y, m - 1, d, 12)));
}
/** Start of a day key in tz, as UTC ISO. */
export function dayStartIso(key: string, tz: string): string {
  const { y, m, d } = parseDayKey(key);
  return zonedToUtc(y, m, d, 0, 0, tz).toISOString();
}

/** ISO → value for <input type="datetime-local"> in tz. */
export function toLocalInput(iso: string | Date | null | undefined, tz: string): string {
  if (!iso) return "";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "";
  const p = tzParts(d, tz);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}T${pad(p.hour)}:${pad(p.minute)}`;
}
/** <input type="datetime-local"> value interpreted in tz → ISO UTC. */
export function fromLocalInput(value: string, tz: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!m) return null;
  return zonedToUtc(Number(m[1]), Number(m[2]), Number(m[3]), Number(m[4]), Number(m[5]), tz).toISOString();
}
export function timeLabel(iso: string, tz: string): string {
  const p = tzParts(new Date(iso), tz);
  return `${pad(p.hour)}:${pad(p.minute)}`;
}

export function browserTz(): string {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; }
}

const FALLBACK_ZONES = [
  "UTC", "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Madrid", "Europe/Amsterdam", "Europe/Stockholm", "Europe/Warsaw",
  "Europe/Athens", "Europe/Istanbul", "Africa/Lagos", "Africa/Johannesburg", "Africa/Cairo", "Asia/Dubai", "Asia/Kolkata",
  "Asia/Singapore", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul", "Australia/Sydney", "Pacific/Auckland", "America/Sao_Paulo",
  "America/Mexico_City", "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Toronto",
];
export function timezoneOptions(extra: (string | null | undefined)[] = []): string[] {
  const set = new Set<string>();
  extra.forEach((z) => z && set.add(z));
  FALLBACK_ZONES.forEach((z) => set.add(z));
  return Array.from(set);
}
