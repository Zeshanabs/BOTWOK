"""Assemble docs/ui-walkthrough.md: for every screen, the wireframe from docs/architecture/24-wireframes.md
side by side with the live screenshot in docs/screenshots/ and what the screen does/how it was verified."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = (ROOT / "docs/architecture/24-wireframes.md").read_text()
SHOTS = ROOT / "docs/screenshots"

# screen number → (title in doc 24, screenshot file, route, what happens on this screen, verification notes)
SCREENS = [
    (1, "Login", "01-login.jpg", "/login", "Email + password sign-in; access token kept in memory, rotating refresh cookie.", "Signed in as the seeded demo user; redirected to the workspace dashboard."),
    (2, "Signup", "02-signup.jpg", "/signup", "Creates the first user, who becomes owner of a new workspace.", "Form renders; signup API covered by integration tests (rotation + reuse detection)."),
    (3, "Onboarding", "03-onboarding.jpg", "/onboarding", "Six-step wizard: workspace → brand → import from website → connect account → goals → done.", "Step 1 renders with slug + timezone defaults; later steps call the brand/import/social APIs."),
    (4, "Workspace", "23-team.jpg", "/w/{slug}/settings/team", "Workspace switcher in the header; members, roles and invitations on the Team page.", "Owner listed with role; invite dialog wired to POST invitations."),
    (5, "Dashboard", "05-dashboard.jpg", "/w/{slug}/dashboard", "KPIs with period comparison, what-to-do-next recommendations, upcoming schedule, pending approvals, recent AI runs, account health.", "All widgets render honest empty states before any data exists; brand selector in header populates metrics."),
    (6, "AI Assistant / Command Center", "06-command-center.jpg", "/w/{slug}/command-center", "Prompt box with slash commands, run timeline (plan checklist with ✓/⟳/✗, durations, cost), sources, reasoning summary, generated content, actions awaiting approval, run history.", "Run started from the UI; without provider keys the run fails fast and the failure is shown in the timeline (transparency contract)."),
    (7, "Research", "07-research.jpg", "/w/{slug}/research", "New run form (query, scope, depth, recency, brand), ranked sources with credibility/relevance badges, source drawer, history.", "Form submits to POST /research/runs; pipeline runs through the worker (search → fetch → extract → dedupe → score → persist)."),
    (8, "Competitors", "08-competitors.jpg", "/w/{slug}/competitors", "Competitor cards with per-platform availability badges (official API / public web / search / user-provided / not collected), sync, compare.", "Empty state explains the no-scraping rule; Add Competitor dialog posts to /competitors and triggers a profile sync."),
    (9, "Competitor Detail", "09-competitor-detail.jpg", "/w/{slug}/competitors/{id}", "Profile cards per platform, tabs Overview · Posts · Pillars & Hooks · Visual & Tone · Website & Blog · News · Gaps & Opportunities · Reports.", "Rendered after adding a competitor with a website profile (public-web availability)."),
    (10, "Trends", "10-trends.jpg", "/w/{slug}/trends", "Trend cards with score, velocity sparkline, platforms, keywords; scan now; create ideas from a trend.", "Empty state + Scan now wired to POST /trends/scan (deterministic burst scoring over research/competitor signals)."),
    (11, "Content Ideas", "11-ideas.jpg", "/w/{slug}/ideas", "Kanban New · Shortlisted · Promoted · Discarded (or table), generate-ideas dialog, promote to Studio.", "Seeded idea appears in the New column with pillar/type/platform tags and a Promote action."),
    (12, "Content Studio", "12-studio-editor.jpg", "/w/{slug}/studio/{id}", "Three columns: navigator (master + platform variants, versions), editor (hook/body/CTA, hashtags, per-platform character budget, preview), right panel (AI, sources, SEO, media, critic, approval, schedule).", "Seeded item opened: master + LinkedIn variant, versions list, 274/3,000 character budget, status chips; autosave shows 'All changes saved'."),
    (13, "Media Library", "13-media.jpg", "/w/{slug}/media", "Grid with filters, upload (presigned PUT), generate image, resize for platform, background removal.", "Empty state renders; upload and generate paths wired to /media routes (S3-compatible store running locally)."),
    (14, "Calendar", "14-calendar.jpg", "/w/{slug}/calendar", "Month/week/day/list/board views, filters, drag-and-drop rescheduling, unscheduled tray, timezone selector, quick create.", "Month view in the brand timezone; the approved LinkedIn post appears in the Unscheduled tray ready to drag onto a day."),
    (15, "Approvals", "15-approvals.jpg", "/w/{slug}/approvals", "Pending inbox grouped by brand, full per-platform preview, risk level, provenance, Approve / Request changes / Reject with comment, bulk approve.", "Approved the seeded LinkedIn item from this screen → content became `approved`, toast 'scheduling is unlocked', inbox emptied."),
    (16, "Publishing", "16-publishing.jpg", "/w/{slug}/publishing", "Queue by status with attempts and next retry, failed/dead-letter actions, published list with platform links/delete, platform health strip.", "Renders with empty queue; health strip reports no connected accounts (OAuth app credentials required)."),
    (17, "Analytics", "17-analytics.jpg", "/w/{slug}/analytics", "KPIs with basis/coverage footnotes, engagement over time, by platform/pillar/format, best-hours heatmap, top posts, insights.", "Shows 'n/a — not provided by the connected platforms' rather than zeros when no metrics exist."),
    (18, "Reports", "18-reports.jpg", "/w/{slug}/reports", "Report list, generate wizard (kind, period, brand, recipients), viewer with sections and sources, export.", "Weekly performance report generated by the worker from stored data (deterministic data pack; AI narrative added when a provider key exists); viewer shows sections, basis/coverage table, export and regenerate."),
    (19, "Automations", "19b-automation-builder.jpg", "/w/{slug}/automations", "Workflow list, React Flow builder with node palette (Trigger, Condition, AI Agent, Research, Generate, Transform, Approve, Schedule, Publish, Wait, Webhook, Notification, Analytics, Action), templates, run history.", "Created the 'Industry news → LinkedIn post' workflow from the server template; the React Flow builder shows the node chain (trend → research → 5 ideas → draft → human approval → schedule), node palette, on-error policy and cost cap; a dry run executed through the worker and paused on its AI step (no provider keys)."),
    (20, "Social Accounts", "20-social-accounts.jpg", "/w/{slug}/settings/social", "Account cards with status/token expiry/scopes/capabilities; connect buttons per platform with real requirement explainers.", "All nine platforms offered; connect flow redirects to the platform's OAuth page once app credentials are set in .env."),
    (21, "Brand Settings", "21-brand-settings.jpg", "/w/{slug}/settings/brand", "Tabs Profile · Audience · Voice & Style · Visual Identity · Content Pillars · Keywords/Hashtags/CTAs · Goals; import from website; preview of the AI context.", "Seeded brand (Acme Billing) with settings and 10 default pillars loaded from the API."),
    (22, "AI Settings", "22-ai-settings.jpg", "/w/{slug}/settings/ai", "Provider keys (stored encrypted, shown as last4), model routing per tier and per agent, local model detection, budgets, safety thresholds, prompt templates, usage/cost dashboard.", "Provider table lists Anthropic/OpenAI/Google/xAI/Tavily/Brave/Exa/ElevenLabs with 'Add key' actions."),
    (23, "Team", "23-team.jpg", "/w/{slug}/settings/team", "Members with role select, invite dialog, pending invitations, role explanations.", "Owner row rendered from GET members."),
    (24, "System Settings", "24-system-settings.jpg", "/w/{slug}/settings/system", "Workspace general, notification channels, API keys, export/backup, danger zone, admin/debug (health, jobs, events, costs).", "General tab renders with timezone, retention and channel toggles; admin panel reads /admin/*."),
]


def section(n: int) -> str:
    m = re.search(rf"^## {n}\. .*?$", WF, flags=re.M)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r"^## \d+\. ", WF[start:], flags=re.M)
    return WF[start : start + nxt.start()] if nxt else WF[start:]


def first_wireframe(sec: str) -> str:
    m = re.search(r"\*\*Layout\*\*.*?```(?:text)?\n(.*?)```", sec, flags=re.S)
    if not m:
        m = re.search(r"```(?:text)?\n(.*?)```", sec, flags=re.S)
    return m.group(1).rstrip() if m else "(no wireframe block found)"


out = ["# Botwok — UI walkthrough: wireframe vs. built screen", "",
       "Each section shows the designed wireframe (from `architecture/24-wireframes.md`) next to a screenshot of the running application, plus what happens on the screen and how it was verified. Screenshots were taken against the local stack (FastAPI + workers + Next.js) on 2026-10-08 with the seeded demo workspace.", ""]
for n, title, shot, route, what, verified in SCREENS:
    sec = section(n)
    wf = first_wireframe(sec)
    has_shot = (SHOTS / shot).exists()
    out += [f"## {n}. {title}", "", f"**Route:** `{route}`  ", f"**What happens here:** {what}  ", f"**Verified:** {verified}", "",
            "<table><tr><th width=\"50%\">Wireframe (design)</th><th width=\"50%\">Built screen</th></tr><tr><td>", "", "```text", wf, "```", "", "</td><td>", "",
            (f"![{title}](screenshots/{shot})" if has_shot else "_(screenshot pending)_"), "", "</td></tr></table>", ""]
(ROOT / "docs/ui-walkthrough.md").write_text("\n".join(out))
print("wrote docs/ui-walkthrough.md with", len(SCREENS), "screens;", sum((SHOTS / s[2]).exists() for s in SCREENS), "screenshots present")
