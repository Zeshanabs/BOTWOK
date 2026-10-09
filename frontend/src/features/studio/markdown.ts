/** Tiny markdown subset <-> HTML/ProseMirror JSON bridge for the body editor (no extra deps). */

export interface PMMark { type: string; attrs?: Record<string, unknown> }
export interface PMNode { type: string; text?: string; marks?: PMMark[]; attrs?: Record<string, unknown>; content?: PMNode[] }

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export function inlineMdToHtml(s: string): string {
  let out = esc(s);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*(?!\s)(.+?)\*/g, "$1<em>$2</em>");
  out = out.replace(/~~(.+?)~~/g, "<s>$1</s>");
  out = out.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2">$1</a>');
  return out;
}

export function mdToHtml(md: string): string {
  const lines = (md ?? "").replace(/\r\n/g, "\n").split("\n");
  const html: string[] = [];
  let para: string[] = [];
  let list: { kind: "ul" | "ol"; items: string[] } | null = null;
  let quote: string[] = [];
  const flushPara = () => { if (para.length) { html.push(`<p>${para.map(inlineMdToHtml).join("<br>")}</p>`); para = []; } };
  const flushList = () => { if (list) { html.push(`<${list.kind}>${list.items.map((i) => `<li><p>${inlineMdToHtml(i)}</p></li>`).join("")}</${list.kind}>`); list = null; } };
  const flushQuote = () => { if (quote.length) { html.push(`<blockquote><p>${quote.map(inlineMdToHtml).join("<br>")}</p></blockquote>`); quote = []; } };
  const flushAll = () => { flushPara(); flushList(); flushQuote(); };
  for (const raw of lines) {
    const line = raw.trimEnd();
    let m: RegExpExecArray | null;
    if (!line.trim()) { flushAll(); continue; }
    if ((m = /^(#{1,3})\s+(.*)$/.exec(line))) { flushAll(); html.push(`<h${m[1].length}>${inlineMdToHtml(m[2])}</h${m[1].length}>`); continue; }
    if ((m = /^\s*[-*•]\s+(.*)$/.exec(line))) { flushPara(); flushQuote(); if (!list || list.kind !== "ul") { flushList(); list = { kind: "ul", items: [] }; } list.items.push(m[1]); continue; }
    if ((m = /^\s*\d+[.)]\s+(.*)$/.exec(line))) { flushPara(); flushQuote(); if (!list || list.kind !== "ol") { flushList(); list = { kind: "ol", items: [] }; } list.items.push(m[1]); continue; }
    if ((m = /^>\s?(.*)$/.exec(line))) { flushPara(); flushList(); quote.push(m[1]); continue; }
    flushList(); flushQuote();
    para.push(line);
  }
  flushAll();
  return html.join("") || "<p></p>";
}

function inlineToMd(nodes: PMNode[] | undefined): string {
  if (!nodes) return "";
  return nodes.map((n) => {
    if (n.type === "hardBreak") return "\n";
    if (n.type !== "text") return inlineToMd(n.content);
    let t = n.text ?? "";
    for (const mk of n.marks ?? []) {
      if (mk.type === "bold") t = `**${t}**`;
      else if (mk.type === "italic") t = `*${t}*`;
      else if (mk.type === "code") t = `\`${t}\``;
      else if (mk.type === "strike") t = `~~${t}~~`;
      else if (mk.type === "link" && typeof mk.attrs?.href === "string") t = `[${t}](${mk.attrs.href})`;
    }
    return t;
  }).join("");
}

function blockToMd(n: PMNode): string {
  switch (n.type) {
    case "paragraph": return inlineToMd(n.content);
    case "heading": return `${"#".repeat(Number(n.attrs?.level ?? 2))} ${inlineToMd(n.content)}`;
    case "bulletList": return (n.content ?? []).map((li) => `- ${(li.content ?? []).map(blockToMd).join(" ")}`).join("\n");
    case "orderedList": return (n.content ?? []).map((li, i) => `${i + 1}. ${(li.content ?? []).map(blockToMd).join(" ")}`).join("\n");
    case "blockquote": return (n.content ?? []).map(blockToMd).join("\n").split("\n").map((l) => `> ${l}`).join("\n");
    case "codeBlock": return `\`\`\`\n${inlineToMd(n.content)}\n\`\`\``;
    case "horizontalRule": return "---";
    default: return n.content ? n.content.map(blockToMd).join("\n\n") : "";
  }
}

export function pmToMd(doc: PMNode): string {
  return (doc.content ?? []).map(blockToMd).join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
}
