"""Deterministic report rendering (doc 13 §13.6, doc 06 ``report``): data pack → sections (Markdown + chart specs) →
full Markdown / standalone HTML (inline CSS, no external assets). Pure functions: no DB, no network.

Every number comes from the data pack; missing values render as "n/a" (never 0) and coverage is stated.
"""
from __future__ import annotations

import html as _html
import re
from typing import Any

KIND_LABELS = {"weekly_performance": "Weekly performance report", "competitor": "Competitor report",
               "competitor_opportunities": "Competitor opportunities", "campaign": "Campaign report",
               "research_brief": "Research brief", "custom": "Report"}
KPI_ROWS = (("posts_published", "Posts published", "int"), ("impressions", "Impressions", "int"), ("reach", "Reach", "int"),
            ("views", "Views", "int"), ("engagement", "Engagements", "int"), ("engagement_rate", "Engagement rate", "rate"),
            ("likes", "Likes", "int"), ("comments", "Comments", "int"), ("shares", "Shares", "int"), ("saves", "Saves", "int"),
            ("clicks", "Clicks", "int"), ("link_clicks", "Link clicks", "int"), ("follows_from_post", "Follows from posts", "int"))
CORE_KPIS = {"posts_published", "impressions", "reach", "views", "engagement", "engagement_rate"}
PLATFORM_LABELS = {"facebook": "Facebook", "instagram": "Instagram", "threads": "Threads", "linkedin": "LinkedIn", "x": "X",
                   "tiktok": "TikTok", "youtube": "YouTube", "pinterest": "Pinterest", "gbp": "Google Business Profile",
                   "website": "Website", "blog": "Blog", "rss": "RSS"}
NA = "n/a"


# ------------------------------------------------------------------------------------------------ formatting
def fmt_int(v: Any) -> str:
    if v is None:
        return NA
    try:
        f = float(v)
    except (TypeError, ValueError):
        return NA
    return f"{int(round(f)):,}" if abs(f - round(f)) < 1e-9 or abs(f) >= 100 else f"{f:,.1f}"


def fmt_rate(v: Any) -> str:
    if v is None:
        return NA
    return f"{float(v) * 100:.2f}%"


def fmt_delta(v: Any) -> str:
    if v is None:
        return NA
    pct = float(v) * 100
    sign = "+" if pct > 0 else ("−" if pct < 0 else "±")
    return f"{sign}{abs(pct):.1f}%"


def fmt_value(v: Any, kind: str) -> str:
    return fmt_rate(v) if kind == "rate" else fmt_int(v)


def platform_label(p: Any) -> str:
    return PLATFORM_LABELS.get(str(p or ""), str(p or NA))


def _http(url: Any) -> bool:
    return isinstance(url, str) and url.lower().startswith(("http://", "https://")) and " " not in url and ")" not in url


def cell(v: Any) -> str:
    s = "" if v is None else str(v)
    return s.replace("|", "\\|").replace("\n", " ").strip() or NA


def table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(cell(h) for h in headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _basis_text(basis: Any) -> str:
    if isinstance(basis, dict):
        return ", ".join(f"{k}: {v}" for k, v in sorted(basis.items())) or NA
    return str(basis) if basis else NA


def _period_text(pack: dict[str, Any]) -> str:
    p = pack.get("period") or {}
    return f"{p.get('start', '?')} → {p.get('end', '?')}"


# ------------------------------------------------------------------------------------------------ sections
def section(heading: str, markdown: str, *, charts: list[dict[str, Any]] | None = None, sources: list[str] | None = None,
            origin: str = "data") -> dict[str, Any]:
    return {"heading": heading, "markdown": markdown.strip(), "charts": charts or [], "sources": sources or [], "origin": origin}


def kpi_section(pack: dict[str, Any]) -> dict[str, Any] | None:
    k = pack.get("kpis")
    if not k:
        return None
    rows = []
    for key, label, kind in KPI_ROWS:
        m = k.get(key)
        if not m:
            continue
        if key not in CORE_KPIS and m.get("value") is None and m.get("previous") is None:
            continue    # secondary metric nobody reports: keep the table short (core metrics always show n/a)
        cov = m.get("coverage")
        posts = (k.get("posts_published") or {}).get("value")
        cov_txt = f"{cov}/{fmt_int(posts)} posts" if key not in ("posts_published",) and cov is not None else "—"
        rows.append([label, fmt_value(m.get("value"), kind), fmt_value(m.get("previous"), kind), fmt_delta(m.get("delta_pct")),
                     cov_txt, _basis_text(m.get("basis")) if key == "engagement_rate" else m.get("basis") or "—"])
    prev = pack.get("previous_period") or {}
    md = (f"Period {_period_text(pack)} compared with the previous period "
          f"{prev.get('start', '?')} → {prev.get('end', '?')}.\n\n"
          + table(["Metric", "This period", "Previous", "Change", "Coverage", "Basis"], rows)
          + "\n\nMissing metrics are shown as n/a (not zero); coverage counts the posts that report the metric.")
    chart_keys = [r for r in ("impressions", "views", "engagement") if (k.get(r) or {}).get("value") is not None]
    charts = []
    if chart_keys:
        charts.append({"type": "bar", "title": "This period vs previous", "x": chart_keys,
                       "series": [{"name": "This period", "data": [k[c]["value"] for c in chart_keys]},
                                  {"name": "Previous", "data": [k[c].get("previous") for c in chart_keys]}]})
    trend = pack.get("trend") or {}
    if len(trend.get("points") or []) >= 2:
        charts.append({"type": "line", "title": f"{trend.get('metric', 'metric').replace('_', ' ')} by {trend.get('granularity', 'week')}",
                       "x": [p["period"] for p in trend["points"]],
                       "series": [{"name": "mean", "data": [p["mean"] for p in trend["points"]]},
                                  {"name": "posts", "data": [p["n"] for p in trend["points"]]}]})
    return section("Highlights", md, charts=charts)


def accounts_section(pack: dict[str, Any]) -> dict[str, Any] | None:
    accs = pack.get("accounts") or []
    if not accs:
        return None
    rows = []
    for a in accs:
        f = a.get("followers") or {}
        rows.append([platform_label(a.get("platform")), a.get("display_name") or a.get("handle"), fmt_int(f.get("end")),
                     fmt_int(f.get("delta")) if f.get("delta") is None or f["delta"] <= 0 else "+" + fmt_int(f["delta"]),
                     fmt_int((a.get("impressions") or {}).get("value")), fmt_int((a.get("views") or {}).get("value")),
                     a.get("status") or NA])
    return section("Accounts", table(["Platform", "Account", "Followers", "Change", "Impressions", "Views", "Status"], rows))


def top_posts_section(pack: dict[str, Any]) -> dict[str, Any] | None:
    tp = pack.get("top_posts") or {}
    posts = tp.get("posts") or []
    if not posts:
        return None
    metric = tp.get("metric", "engagement_rate")
    lines = []
    for i, p in enumerate(posts, 1):
        val = fmt_rate(p.get("value")) if metric == "engagement_rate" else fmt_int(p.get("value"))
        title = p.get("title") or (p.get("text") or "").split("\n")[0][:90] or "(untitled)"
        link = f" — [view]({p['url']})" if _http(p.get("url")) else ""
        lines.append(f"{i}. **{title}** · {platform_label(p.get('platform'))} · {p.get('format') or NA} · "
                     f"{metric.replace('_', ' ')} {val} · {str(p.get('published_at', ''))[:10]}{link}")
    cov = tp.get("coverage") or {}
    md = "\n".join(lines) + f"\n\nRanked by {metric.replace('_', ' ')} ({cov.get('with_metric', 0)} of {cov.get('posts', 0)} posts measured)."
    return section("Top posts", md)


def insights_section(pack: dict[str, Any], *, kinds: tuple[str, ...] | None = None, heading: str = "Insights") -> dict[str, Any] | None:
    items = [i for i in pack.get("insights") or [] if not kinds or i.get("kind") in kinds]
    if not items:
        return None
    lines = [f"- {i['statement']} _({i.get('kind')}, {i.get('confidence')} confidence"
             + (f", n={i['n']}" if i.get("n") is not None else "") + ")_" for i in items]
    return section(heading, "\n".join(lines))


def recommendations_section(pack: dict[str, Any], *, heading: str = "Recommendations",
                            only_competitor: bool = False) -> dict[str, Any] | None:
    items = pack.get("recommendations") or []
    if only_competitor:
        items = [r for r in items if (r.get("target") or {}).get("competitor_id")]
    if not items:
        return None
    lines = []
    for r in items:
        extra = f" — expected impact: {r['expected_impact']}" if r.get("expected_impact") else ""
        lines.append(f"- **[{(r.get('priority') or 'p2').upper()}]** {r['action']} _({r.get('status', 'proposed')})_{extra}")
    return section(heading, "\n".join(lines))


def competitors_section(pack: dict[str, Any]) -> dict[str, Any] | None:
    comps = pack.get("competitors") or []
    if not comps:
        return None
    rows = []
    for c in comps:
        ppw, fol = c.get("posts_per_week") or {}, c.get("followers") or {}
        rows.append([c.get("name"), platform_label(c.get("platform")), fmt_int(ppw.get("before")), fmt_int(ppw.get("after")),
                     fmt_int(fol.get("before")), fmt_int(fol.get("after")), c.get("snapshots", 0), c.get("availability") or NA])
    md = (table(["Competitor", "Channel", "Posts/wk (start)", "Posts/wk (end)", "Followers (start)", "Followers (end)",
                 "Snapshots", "Data"], rows)
          + "\n\nStart values need at least two snapshots in the period; otherwise they are n/a.")
    charts = []
    with_after = [c for c in comps if (c.get("posts_per_week") or {}).get("after") is not None]
    if with_after:
        charts.append({"type": "bar", "title": "Posts per week (latest snapshot)",
                       "x": [f"{c.get('name')} · {platform_label(c.get('platform'))}" for c in with_after],
                       "series": [{"name": "posts/week", "data": [c["posts_per_week"]["after"] for c in with_after]}]})
    return section("Competitor activity", md, charts=charts)


def competitor_analyses_section(pack: dict[str, Any]) -> dict[str, Any] | None:
    analyses = pack.get("competitor_analyses") or []
    lines = []
    for a in analyses:
        opps = a.get("opportunities") or []
        for o in opps[:6]:
            text = o.get("text") or o.get("opportunity") or o.get("title") if isinstance(o, dict) else str(o)
            if text:
                lines.append(f"- {text} _(from the {a.get('competitor_name') or 'competitor'} analysis, "
                             f"{str(a.get('created_at', ''))[:10]})_")
    if not lines:
        return None
    return section("Opportunities from competitor analyses", "\n".join(lines))


def upcoming_section(pack: dict[str, Any]) -> dict[str, Any] | None:
    up = pack.get("upcoming")
    if up is None:
        return None
    if not up:
        return section("Upcoming schedule", "Nothing is scheduled for the next 7 days.")
    rows = [[str(u.get("scheduled_at", ""))[:16].replace("T", " "), platform_label(u.get("platform")), u.get("format"),
             u.get("title"), u.get("status")] for u in up]
    return section("Upcoming schedule", table(["When (UTC)", "Platform", "Format", "Content", "Status"], rows))


def research_section(pack: dict[str, Any]) -> dict[str, Any] | None:
    runs = pack.get("research") or []
    if not runs:
        return None
    parts, sources = [], []
    for r in runs:
        parts.append(f"### {r.get('query') or 'Research run'}\n\n_{r.get('status')} · {str(r.get('created_at', ''))[:10]}_")
        if r.get("summary"):
            parts.append(str(r["summary"]))
        srcs = (r.get("sources") or [])[:8]
        index = {str(x.get("source_id")): n for n, x in enumerate(srcs, 1)}
        bullets = []
        for f in (r.get("findings") or [])[:5]:
            refs = "".join(f"[{index[str(sid)]}]" for sid in (f.get("source_ids") or []) if str(sid) in index)
            bullets.append(f"- {f.get('text')}" + (f" {refs}" if refs else ""))
        if bullets:
            parts.append("\n".join(bullets))
        src_lines = []
        for n, s in enumerate(srcs, 1):
            sources.append(str(s.get("source_id")))
            cred = f" · credibility {float(s['credibility']):.2f}" if s.get("credibility") is not None else ""
            title = s.get("title") or s.get("url")
            src_lines.append(f"{n}. [{cell(title)}]({s.get('url')}) · {s.get('domain') or NA}{cred}" if _http(s.get("url"))
                             else f"{n}. {cell(title)}{cred}")
        if src_lines:
            parts.append("**Sources**\n\n" + "\n".join(src_lines))
    return section("Research", "\n\n".join(parts), sources=[s for s in sources if s and s != "None"])


def campaigns_section(pack: dict[str, Any]) -> dict[str, Any] | None:
    camps = pack.get("campaigns")
    if camps is None:
        return None
    if not camps:
        return section("Campaigns", "No campaign was active in this period.")
    rows = []
    for c in camps:
        k = c.get("kpis") or {}
        rows.append([c.get("name"), c.get("status"), f"{c.get('starts_on') or '…'} → {c.get('ends_on') or '…'}",
                     fmt_int((k.get("posts_published") or {}).get("value")), fmt_int((k.get("impressions") or {}).get("value")),
                     fmt_int((k.get("engagement") or {}).get("value")), fmt_rate((k.get("engagement_rate") or {}).get("value"))])
    md = table(["Campaign", "Status", "Dates", "Posts", "Impressions", "Engagements", "Engagement rate"], rows)
    goals = [f"- **{c.get('name')}**: {c['goal']}" for c in camps if c.get("goal")]
    if goals:
        md += "\n\n**Goals**\n\n" + "\n".join(goals)
    return section("Campaigns", md)


def data_notes_section(pack: dict[str, Any]) -> dict[str, Any] | None:
    notes = pack.get("data_notes") or []
    if not notes:
        return None
    return section("Data notes", "\n".join(f"- {n}" for n in notes))


SECTION_BUILDERS: dict[str, tuple[Any, ...]] = {
    "weekly_performance": (kpi_section, accounts_section, top_posts_section, insights_section, recommendations_section,
                           competitors_section, upcoming_section, data_notes_section),
    "competitor": (competitors_section, lambda p: insights_section(p, kinds=("competitor",), heading="Competitor insights"),
                   competitor_analyses_section, kpi_section, data_notes_section),
    "competitor_opportunities": (competitor_analyses_section,
                                 lambda p: recommendations_section(p, heading="Recommended responses", only_competitor=True),
                                 lambda p: insights_section(p, kinds=("competitor",), heading="Competitor insights"),
                                 competitors_section, data_notes_section),
    "campaign": (campaigns_section, kpi_section, top_posts_section, upcoming_section, data_notes_section),
    "research_brief": (research_section, insights_section, data_notes_section),
    "custom": (kpi_section, top_posts_section, insights_section, recommendations_section, competitors_section,
               research_section, upcoming_section, data_notes_section),
}


def build_sections(kind: str, pack: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for builder in SECTION_BUILDERS.get(kind, SECTION_BUILDERS["custom"]):
        s = builder(pack)
        if s:
            out.append(s)
    if not out:
        out.append(section("Summary", "No data was available for this period."))
    return out


def build_summary(kind: str, pack: dict[str, Any]) -> str:
    """Headline sentence(s) from the numbers (deterministic)."""
    brand = (pack.get("brand") or {}).get("name") or "The brand"
    period = _period_text(pack)
    parts: list[str] = []
    k = pack.get("kpis") or {}
    if kind in ("weekly_performance", "custom", "campaign") and k:
        posts = (k.get("posts_published") or {}).get("value") or 0
        parts.append(f"{brand} published {fmt_int(posts)} post(s) in {period}.")
        er = k.get("engagement_rate") or {}
        if er.get("value") is not None:
            delta = f", {fmt_delta(er['delta_pct'])} vs the previous period" if er.get("delta_pct") is not None else ""
            parts.append(f"Engagement rate averaged {fmt_rate(er['value'])}{delta} ({er.get('coverage', 0)} of {fmt_int(posts)} "
                         "posts measured).")
        for key, label in (("impressions", "Impressions"), ("views", "Views")):
            m = k.get(key) or {}
            if m.get("value") is not None:
                delta = f" ({fmt_delta(m['delta_pct'])})" if m.get("delta_pct") is not None else ""
                parts.append(f"{label} totalled {fmt_int(m['value'])}{delta}.")
                break
    if kind == "campaign":
        parts.append(f"{len(pack.get('campaigns') or [])} campaign(s) were active.")
    if kind in ("competitor", "competitor_opportunities"):
        comps = pack.get("competitors") or []
        names = sorted({c.get("name") for c in comps if c.get("name")})
        parts.append(f"{len(names)} competitor(s) tracked in {period}" + (f": {', '.join(names[:5])}." if names else "."))
        movers = [c for c in comps if (c.get("posts_per_week") or {}).get("before") is not None
                  and (c.get("posts_per_week") or {}).get("after") is not None
                  and c["posts_per_week"]["after"] != c["posts_per_week"]["before"]]
        if movers:
            c = max(movers, key=lambda c: abs(c["posts_per_week"]["after"] - c["posts_per_week"]["before"]))
            parts.append(f"Largest cadence change: {c.get('name')} on {platform_label(c.get('platform'))} "
                         f"({fmt_int(c['posts_per_week']['before'])} → {fmt_int(c['posts_per_week']['after'])} posts/week).")
    if kind == "research_brief":
        runs = pack.get("research") or []
        n_src = sum(len(r.get("sources") or []) for r in runs)
        parts.append(f"{len(runs)} research run(s) in {period} with {n_src} cited source(s).")
    ins, recs = pack.get("insights") or [], pack.get("recommendations") or []
    if (ins or recs) and kind != "research_brief":
        parts.append(f"{len(ins)} insight(s) and {len(recs)} recommendation(s) apply to this period.")
    up = pack.get("upcoming")
    if up is not None and kind in ("weekly_performance", "custom", "campaign"):
        parts.append(f"{len(up)} post(s) are scheduled for the next 7 days.")
    return " ".join(parts) or f"No data was available for {period}."


def narrative_section(narrative: dict[str, Any]) -> dict[str, Any] | None:
    """The report agent's narrative as one AI-marked section (summary + its own sections as sub-headings)."""
    if not narrative:
        return None
    parts = [str(narrative.get("summary") or "").strip()]
    sources: list[str] = []
    charts: list[dict[str, Any]] = []
    for s in narrative.get("sections") or []:
        if not isinstance(s, dict) or not s.get("markdown"):
            continue
        parts.append(f"### {s.get('heading') or 'Notes'}\n\n{str(s['markdown']).strip()}")
        sources += [str(x) for x in s.get("sources") or []]
        charts += [c for c in s.get("charts") or [] if isinstance(c, dict)]
    md = "\n\n".join(p for p in parts if p)
    if not md:
        return None
    return section("Narrative summary ✦", md, charts=charts[:6], sources=sorted(set(sources)), origin="ai")


def compose(title: str, kind: str, pack: dict[str, Any], *, narrative: dict[str, Any] | None = None) -> dict[str, Any]:
    """→ {summary, summary_deterministic, sections, markdown, html}."""
    sections = build_sections(kind, pack)
    det_summary = build_summary(kind, pack)
    ns = narrative_section(narrative or {})
    if ns:
        sections = [ns] + sections
    summary = (narrative or {}).get("summary") or det_summary
    meta = {"kind": kind, "period": pack.get("period") or {}, "brand": (pack.get("brand") or {}).get("name"),
            "generated_at": pack.get("generated_at"), "data_pack_version": pack.get("version")}
    md = render_markdown(title, summary, sections, meta)
    return {"summary": summary, "summary_deterministic": det_summary, "sections": sections, "markdown": md,
            "html": render_html(title, summary, sections, meta)}


# ------------------------------------------------------------------------------------------------ markdown / html
def _meta_line(meta: dict[str, Any]) -> str:
    p = meta.get("period") or {}
    bits = [KIND_LABELS.get(meta.get("kind") or "", "Report")]
    if meta.get("brand"):
        bits.append(str(meta["brand"]))
    if p.get("start") or p.get("end"):
        bits.append(f"{p.get('start', '?')} → {p.get('end', '?')}")
    if meta.get("generated_at"):
        bits.append(f"generated {str(meta['generated_at'])[:16].replace('T', ' ')} UTC")
    return " · ".join(bits)


def render_markdown(title: str, summary: str | None, sections: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    out = [f"# {title}", "", f"_{_meta_line(meta)}_", ""]
    if summary:
        out += ["## Summary", "", summary.strip(), ""]
    for s in sections:
        out += [f"## {s.get('heading') or 'Section'}", "", str(s.get("markdown") or "").strip(), ""]
        if s.get("sources"):
            out += ["Sources: " + ", ".join(f"`{x}`" for x in s["sources"]), ""]
    out.append("---")
    out.append(f"Generated by Botwok (data pack v{meta.get('data_pack_version') or 1}). Numbers come from stored metrics; "
               "n/a means the platform does not report the metric or it was not collected.")
    return "\n".join(out).strip() + "\n"


_SAFE_URL = re.compile(r"^(https?://|/|#|mailto:)", re.I)
STYLE = {
    "table": "border-collapse:collapse;width:100%;margin:12px 0;font-size:13px",
    "th": "border:1px solid #e2e8f0;padding:6px 8px;text-align:left;background:#f8fafc;font-weight:600",
    "td": "border:1px solid #e2e8f0;padding:6px 8px;text-align:left;vertical-align:top",
    "code": "font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;background:#f1f5f9;padding:1px 4px;border-radius:4px",
    "blockquote": "border-left:3px solid #cbd5e1;margin:8px 0;padding:4px 12px;color:#475569",
    "a": "color:#2563eb",
}


def _inline(text: str) -> str:
    s = _html.escape(text, quote=True)
    codes: list[str] = []

    def keep_code(m: re.Match[str]) -> str:
        codes.append(f'<code style="{STYLE["code"]}">{m.group(1)}</code>')
        return f"\x00{len(codes) - 1}\x00"

    s = re.sub(r"`([^`]+)`", keep_code, s)

    def link(m: re.Match[str]) -> str:
        label, url = m.group(1), _html.unescape(m.group(2)).strip()
        if not _SAFE_URL.match(url):
            return label
        return f'<a href="{_html.escape(url, quote=True)}" style="{STYLE["a"]}">{label}</a>'

    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"(?<![\w])_(?!\s)(.+?)(?<!\s)_(?![\w])", r"<em>\1</em>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], s)


def _split_row(line: str) -> list[str]:
    raw = line.strip().strip("|")
    cells, cur, esc = [], "", False
    for ch in raw:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
    cells.append(cur.strip())
    return cells


def markdown_to_html(md: str) -> str:
    """Minimal, safe Markdown → HTML (headings, paragraphs, lists, tables, quotes, rules, bold/italic/code/links).
    All text is HTML-escaped; only http(s)/relative/mailto links are kept."""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            out.append("<p>" + "<br>".join(_inline(x) for x in para) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush()
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush()
            level = len(m.group(1))
            out.append(f"<h{level}>{_inline(m.group(2).strip())}</h{level}>")
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,})$", stripped):
            flush()
            out.append('<hr style="border:none;border-top:1px solid #e2e8f0;margin:20px 0">')
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{3,}", lines[i + 1].strip()):
            flush()
            headers = _split_row(stripped)
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                body.append(_split_row(lines[i]))
                i += 1
            th = "".join(f'<th style="{STYLE["th"]}">{_inline(h)}</th>' for h in headers)
            trs = "".join("<tr>" + "".join(f'<td style="{STYLE["td"]}">{_inline(c)}</td>' for c in r) + "</tr>" for r in body)
            out.append(f'<table style="{STYLE["table"]}"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>')
            continue
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+\.\s+", stripped):
            flush()
            ordered = bool(re.match(r"^\d+\.\s+", stripped))
            pat = r"^\d+\.\s+(.*)$" if ordered else r"^[-*]\s+(.*)$"
            items = []
            while i < len(lines) and re.match(pat, lines[i].strip()):
                items.append(re.match(pat, lines[i].strip()).group(1))  # type: ignore[union-attr]
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f'<blockquote style="{STYLE["blockquote"]}">' + "<br>".join(_inline(q) for q in quote) + "</blockquote>")
            continue
        para.append(stripped)
        i += 1
    flush()
    return "\n".join(out)


_CSS = (
    "body{margin:0;background:#ffffff;color:#0f172a;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
    "Helvetica,Arial,sans-serif;font-size:14px;line-height:1.55}"
    ".wrap{max-width:860px;margin:0 auto;padding:32px 20px}"
    "h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px;padding-bottom:4px;border-bottom:1px solid #e2e8f0}"
    "h3{font-size:15px;margin:18px 0 6px}ul,ol{padding-left:22px}li{margin:3px 0}"
    ".meta{color:#64748b;font-size:12px;margin:0 0 16px}"
    ".summary{background:#f1f5f9;border-radius:12px;padding:12px 16px;margin:16px 0}"
    ".ai{border-left:3px solid #8b5cf6;padding-left:12px}"
    ".sources{color:#64748b;font-size:12px}.foot{color:#94a3b8;font-size:12px;margin-top:32px}"
)


def render_html(title: str, summary: str | None, sections: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> str:
    meta = meta or {}
    body = [f'<h1 style="font-size:24px;margin:0 0 4px">{_html.escape(title)}</h1>',
            f'<p class="meta" style="color:#64748b;font-size:12px">{_html.escape(_meta_line(meta))}</p>']
    if summary:
        body.append('<div class="summary" style="background:#f1f5f9;border-radius:12px;padding:12px 16px;margin:16px 0">'
                    f"{markdown_to_html(summary)}</div>")
    for s in sections:
        cls = "section ai" if s.get("origin") == "ai" else "section"
        inner = markdown_to_html(str(s.get("markdown") or ""))
        src = ""
        if s.get("sources"):
            src = '<p class="sources">Sources: ' + ", ".join(_html.escape(str(x)) for x in s["sources"]) + "</p>"
        body.append(f'<section class="{cls}"><h2>{_html.escape(str(s.get("heading") or "Section"))}</h2>{inner}{src}</section>')
    body.append(f'<p class="foot">Generated by Botwok · data pack v{_html.escape(str(meta.get("data_pack_version") or 1))} · '
                "n/a = metric not reported by the platform or not collected (never zero).</p>")
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{_html.escape(title)}</title><style>{_CSS}</style></head>"
            f"<body><div class=\"wrap\">{''.join(body)}</div></body></html>\n")
