import { Fragment, type ReactNode } from "react";

/** Minimal markdown → React (headings, paragraphs, lists, quotes, tables, bold/italic/code/links, [n] citations). No HTML injection. */
function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\((?:https?:\/\/|\/)[^)\s]+\)|\[\d+(?:,\s*\d+)*\])/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    const k = `${keyBase}-${i++}`;
    if (t.startsWith("**")) out.push(<strong key={k}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={k} className="rounded bg-muted px-1 text-[0.9em]">{t.slice(1, -1)}</code>);
    else if (t.startsWith("*")) out.push(<em key={k}>{t.slice(1, -1)}</em>);
    else if (/^\[\d/.test(t)) {
      const nums = t.slice(1, -1).split(/,\s*/);
      out.push(<sup key={k}>{nums.map((n, j) => <Fragment key={n}>{j > 0 && ","}<a href={`#src-${n}`} className="text-primary hover:underline">[{n}]</a></Fragment>)}</sup>);
    } else {
      const mm = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(t);
      if (mm) out.push(<a key={k} href={mm[2]} target={mm[2].startsWith("http") ? "_blank" : undefined} rel="noreferrer" className="text-primary underline-offset-2 hover:underline">{mm[1]}</a>);
      else out.push(t);
    }
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function MarkdownView({ markdown, className }: { markdown: string; className?: string }) {
  const lines = (markdown ?? "").replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const cls = level <= 2 ? "mt-4 text-base font-semibold" : "mt-3 text-sm font-semibold";
      blocks.push(level <= 2 ? <h3 key={key++} className={cls}>{inline(h[2], `h${key}`)}</h3> : <h4 key={key++} className={cls}>{inline(h[2], `h${key}`)}</h4>);
      i++; continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        if (!/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().slice(1, -1).split("|").map((c) => c.trim()));
        i++;
      }
      const [head, ...body] = rows;
      blocks.push(
        <div key={key++} className="my-3 overflow-x-auto"><table className="w-full text-sm"><thead><tr>{head?.map((c, j) => <th key={j} className="border-b px-2 py-1 text-left font-medium">{inline(c, `th${key}-${j}`)}</th>)}</tr></thead>
          <tbody>{body.map((r, ri) => <tr key={ri} className="border-b last:border-0">{r.map((c, j) => <td key={j} className="px-2 py-1 tabular-nums">{inline(c, `td${key}-${ri}-${j}`)}</td>)}</tr>)}</tbody></table></div>,
      );
      continue;
    }
    if (/^\s*[-*•]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items: string[] = [];
      while (i < lines.length && (ordered ? /^\s*\d+[.)]\s+/.test(lines[i]) : /^\s*[-*•]\s+/.test(lines[i]))) { items.push(lines[i].replace(/^\s*(?:[-*•]|\d+[.)])\s+/, "")); i++; }
      const List = ordered ? "ol" : "ul";
      blocks.push(<List key={key++} className={`my-2 space-y-1 pl-5 text-sm ${ordered ? "list-decimal" : "list-disc"}`}>{items.map((it, j) => <li key={j}>{inline(it, `li${key}-${j}`)}</li>)}</List>);
      continue;
    }
    if (/^>\s?/.test(line)) {
      const q: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { q.push(lines[i].replace(/^>\s?/, "")); i++; }
      blocks.push(<blockquote key={key++} className="my-2 border-l-2 pl-3 text-sm text-muted-foreground">{inline(q.join(" "), `q${key}`)}</blockquote>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*[-*•]\s|\s*\d+[.)]\s|>|\s*\|)/.test(lines[i])) { para.push(lines[i]); i++; }
    if (!para.length) { para.push(line); i++; }
    blocks.push(<p key={key++} className="my-2 text-sm leading-relaxed">{inline(para.join(" "), `p${key}`)}</p>);
  }
  return <div className={className}>{blocks}</div>;
}
