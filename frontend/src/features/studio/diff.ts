/** Word-level LCS diff for the version compare view. */
export interface DiffPart { kind: "same" | "add" | "del"; text: string }

function tokenize(s: string): string[] {
  return s.split(/(\s+)/).filter((t) => t.length > 0);
}

export function wordDiff(a: string, b: string): DiffPart[] {
  const x = tokenize(a);
  const y = tokenize(b);
  // Guard against quadratic blow-up on very long bodies.
  if (x.length * y.length > 4_000_000) return [{ kind: "del", text: a }, { kind: "add", text: b }];
  const dp: number[][] = Array.from({ length: x.length + 1 }, () => new Array<number>(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    const last = out[out.length - 1];
    if (last && last.kind === kind) last.text += text;
    else out.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { push("same", x[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { push("del", x[i]); i++; }
    else { push("add", y[j]); j++; }
  }
  while (i < x.length) push("del", x[i++]);
  while (j < y.length) push("add", y[j++]);
  return out;
}

/** Flatten a version snapshot to comparable text. */
export function snapshotText(snap: Record<string, unknown>): string {
  const body = (typeof snap.body === "object" && snap.body !== null ? snap.body : snap) as Record<string, unknown>;
  const parts: string[] = [];
  const s = (v: unknown) => (typeof v === "string" ? v : "");
  if (s(snap.title)) parts.push(`Title: ${s(snap.title)}`);
  if (s(body.hook)) parts.push(s(body.hook));
  if (s(body.body_md)) parts.push(s(body.body_md));
  if (s(body.cta)) parts.push(s(body.cta));
  if (s(snap.text)) parts.push(s(snap.text));
  if (Array.isArray(snap.segments) && snap.segments.length) parts.push(snap.segments.map((x) => (typeof x === "string" ? x : typeof x === "object" && x && "text" in x ? String((x as { text: unknown }).text) : "")).join("\n---\n"));
  const tags = Array.isArray(body.hashtags) ? body.hashtags : Array.isArray(snap.hashtags) ? snap.hashtags : [];
  if (tags.length) parts.push(`Hashtags ${tags.join(" ")}`);
  return parts.join("\n\n");
}
