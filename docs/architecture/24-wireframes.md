# 24 — Screen Wireframes

Per-screen specification of the Botwok web client for implementers. Names follow `00-canonical-vocabulary.md` (it wins on conflict). Stack: Next.js App Router, shadcn/ui (Button, Card, Table, Tabs, Sheet, Dialog, Command, Badge, Skeleton, Toast, DropdownMenu, Popover, Calendar, Form), Tailwind, TanStack Query, SSE (`GET /api/v1/events/stream`). All wireframes apply to light and dark mode. §0 holds shared conventions; screen sections state only what is specific.

**Notation:** `[Label]` primary Button · `(Label)` secondary/ghost Button · `▾` Select/DropdownMenu · `⋯` overflow menu · `☐ ☑` Checkbox · `◉ ○` RadioGroup · `▸` disclosure · `✦` AI-generated or AI action · `✓` succeeded · `⟳` running · `✗` failed · `⏸` paused/awaiting approval · `○` pending · `⊘` skipped/cancelled · `●` status dot · `▁▃▅▇` sparkline · `▓░` meter. Platform glyphs `fb ig th li x tt yt pi gbp` are wireframe shorthand; code uses the `platform_t` codes (`facebook instagram threads linkedin x tiktok youtube pinterest gbp`).

---

## 0. Global shell and conventions

### 0.1 Desktop shell

All app routes live under `/w/[workspace]/…`; `/login`, `/signup`, `/onboarding` render without the shell; `/` redirects to the last workspace's Dashboard.

```
┌──────────────────────────────┬───────────────────────────────────────────────┬──────────────────┐
│ ▣ Acme Co ▾  ◆ Acme Coffee ▾ │ ⌘K  Search or run a command…                  │ +New▾ ✦ ◔3 (SB)▾ │
├──────────────────────────────┼───────────────────────────────────────────────┼──────────────────┤
│ ▦ Dashboard                  │ Page title         (Secondary) [Primary]      │ AI · ⌘J        ✕ │
│ ✦ Command Center             │ Breadcrumb · Tabs · Filter bar                │ Context chip     │
│ ──────────────────────────── │ ───────────────────────────────────────────── │ Suggestions      │
│ Research                     │                                               │ Thread           │
│ Competitors                  │                                               │ …                │
│ Trends                       │              CONTENT AREA                     │                  │
│ Ideas                        │   12-col grid · max-w 1440 · 24px gutters     │                  │
│ ──────────────────────────── │   page owns its scroll; header is sticky      │                  │
│ Studio                       │                                               │                  │
│ Media Library                │                                               │                  │
│ Calendar                     │                                               │ ┌──────────────┐ │
│ Approvals                 4  │                                               │ │ Ask… / @     │ │
│ Publishing               ●1  │                                               │ └──────────────┘ │
│ ──────────────────────────── │                                               │ $12.40 / $50     │
│ Analytics                    │                                               │                  │
│ Reports                      │                                               │                  │
│ Automations                  │                                               │                  │
│ ──────────────────────────── │                                               │                  │
│ Settings ▸                   │                                               │                  │
│ ◐ Theme          ⇤ Collapse  │                                               │                  │
└──────────────────────────────┴───────────────────────────────────────────────┴──────────────────┘
```

- **Sidebar** (240px): order exactly as vocabulary §10; icon rail at ≤1280px or `[`. Approvals shows the user's pending count; Publishing a red dot when posts failed.
- **Content area**: header row (title, actions), then body; max width 1440px.
- **AI drawer** (400px, resizable): pushes content at ≥1440px, else overlays as a Sheet.

### 0.2 Header

- **Left** (the §10 switcher slot, above the sidebar): workspace switcher (Popover + Command over `GET /api/v1/workspaces`, plus "Workspace overview", "Create workspace") and brand switcher (`GET /api/v1/brands` + "All brands"; Studio and Brand Settings need one brand). Selection is kept in `?brand=` and user prefs.
- **Center**: `⌘K` palette (Command in Dialog) — Navigate, Create, AI (slash command → new Command Center run), Recent, Search (`?q=` on content, competitors, sources, ideas).
- **Right**: `+ New ▾`, `✦` AI drawer, bell (`GET /api/v1/notifications`, `POST /api/v1/notifications/read-all`), user menu (profile, theme, shortcuts, sign out → `POST /api/v1/auth/logout`).
- SSE loss shows an amber strip "Live updates paused — reconnecting…".

### 0.3 Global AI drawer

Contextual assistant on every shell page; a thin client over the Command Center run engine (§6).

```
┌ AI ───────────────────────────── ⤢  ⋯  ✕ ┐
│ Context: Studio › "Q4 launch" › li    ✕  │
│ ──────────────────────────────────────── │
│ Suggested                                │
│ (Shorten for x) (Add 2 sources)          │
│ (Critique this variant)                  │
│ ──────────────────────────────────────── │
│ You  make the hook punchier              │
│ ✦ Rewrote the hook · writer · powerful   │
│ ┌──────────────────────────────────────┐ │
│ │ 1  "Most Q4 plans fail in week one…" │ │
│ │ [Apply] (Compare) (Discard)          │ │
│ └──────────────────────────────────────┘ │
│ ▸ 2 tool calls · 1.2k tok · $0.004       │
│ ┌──────────────────────────────────────┐ │
│ │ ⟳ Run r_01J9… step 2/4 · $0.02       │ │
│ │ (Open in Command Center) (■ Cancel)  │ │
│ └──────────────────────────────────────┘ │
│ ──────────────────────────────────────── │
│ ┌──────────────────────────────────────┐ │
│ │ Ask, /command, @brand, @competitor   │ │
│ └──────────────────────────────────────┘ │
│ (+ ctx) (/)                [Send ⌘↵]     │
│ This month $12.40 of $50  ▓▓▓░░░░░░░     │
└──────────────────────────────────────────┘
```

- **Context chip** (route + selection) is removable and sent as `context` on `POST /api/v1/ai/conversations` / `POST /api/v1/ai/runs`. Suggestions fill the composer; they never execute.
- Data-changing results are cards with `[Apply]`, written through the normal domain route as a version "AI (applied by Sam)"; side effects appear as §6 action cards.
- `⤢` continues the thread in Command Center. Budget meter (`GET /api/v1/ai/usage`) is amber at 80%; at 100% the composer is disabled. Viewers read only.

### 0.4 Routing

Each section lists its routes. Settings: `/w/[ws]/settings/{brand,social-accounts,ai,team,system}`; `/w/[ws]/overview` and `/w/[ws]/admin` are off-sidebar. Filters live in the query string so deep links land pre-filtered.

### 0.5 Status, provenance and data badges

Status chips are `Badge` with dot + text label (color is never the only signal), tokens from vocabulary §11:

| Status | Token | Status | Token |
|---|---|---|---|
| `idea` | slate | `scheduled` | sky |
| `draft` | gray | `queued`, `publishing` | blue (`publishing` pulses) |
| `ai_generated` | violet | `published` | green |
| `needs_review` | amber | `failed` | red |
| `approved` | emerald | `cancelled` | zinc |

States without a §11 token (`rejected`, `archived`, `paused`, `expired`, `revoked`, `disconnected`) use an outline zinc Badge with an icon. Severity: info blue, warning amber, error red, success green. **Provenance chip** `✦ AI` on any AI-produced object; its Popover shows agent id, tier and resolved model, run link, cost. **Data-availability badges**: `Official API`, `Public web`, `Search`, `User-provided`, `Not collected (platform restriction)`.

### 0.6 Empty, loading and error conventions

- **Loading**: geometry-matching Skeletons after 150ms; long jobs show SSE step progress.
- **Empty**: one sentence, one primary action; filter-caused empties offer `(Clear filters)`.
- **Error**: region-scoped destructive `Alert` with `(Retry)` and copyable request ID; full-page only for 404/no access.
- **Toasts**: success 4s; errors persist with `(Details)`; failed optimistic updates roll back with a toast.
- **Permissions**: unusable controls are hidden, or disabled with a tooltip naming the required role.
- **Destructive confirms** name object and consequence; irreversible platform actions require typing the name.

### 0.7 Mobile shell (< 768px)

```
┌───────────────────────────────────┐
│ ◆ Acme Coffee ▾        ⌘  ✦  ◔3   │
├───────────────────────────────────┤
│                                   │
│   single-column content           │
│   cards instead of tables         │
│   filters in a bottom Sheet       │
│                                   │
│                                   │
├───────────────────────────────────┤
│  ⌂      ✎       ▦        ✓4    ≡  │
│ Home Studio  Cal.  Approvals More │
└───────────────────────────────────┘
```

- Tabs: Home (Dashboard), Studio, Calendar, Approvals (badge), More (Sheet: remaining nav, Settings, workspace switcher).
- Dialogs → bottom Sheets (snap 50%/90%); tables → stacked cards; builders read-mostly. Tablet: icon rail, overlay AI drawer.

### 0.8 Keyboard shortcuts

| Keys | Action | Keys | Action |
|---|---|---|---|
| `⌘K` | Command palette | `⌘J` | AI drawer |
| `⌘/` | Shortcut help | `[` | Toggle sidebar |
| `g d` `g c` `g s` | Dashboard, Command Center, Studio | `g l` `g a` `g p` | Calendar, Approvals, Publishing |
| `n` | New (context-sensitive) | `/` | Focus search or composer |
| `j` `k` `x` `Enter` | Next, previous, select, open | `⌘↵` | Submit / send |
| `⌘S` | Save version (Studio) | `⌘.` | Cancel focused AI run |
| `a` `c` `r` | Approve, Request changes, Reject | `Esc` | Close / clear |

Single-key shortcuts are inactive while a text field has focus.

### 0.9 Live updates

One SSE connection per tab; §8 events map to query invalidations (e.g. `POST_RESCHEDULED` → calendar, queue).

---

## 1. Login

Route: `/login` (`?next=` accepts same-origin relative paths only).

#### Purpose
Authenticate and route to the last workspace, or to `/onboarding` if the user has none.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                  ◐ Theme │
│                               ▣ Botwok                                   │
│                ┌──────────────────────────────────────────┐              │
│                │ Sign in                                  │              │
│                │ Email                                    │              │
│                │ ┌──────────────────────────────────────┐ │              │
│                │ │ you@company.com                      │ │              │
│                │ └──────────────────────────────────────┘ │              │
│                │ Password                    (Forgot?)    │              │
│                │ ┌──────────────────────────────────────┐ │              │
│                │ │ ••••••••••••                  ◎ show │ │              │
│                │ └──────────────────────────────────────┘ │              │
│                │ ☐ Keep me signed in on this device       │              │
│                │ [            Sign in                   ] │              │
│                │ No account? (Create one)                 │              │
│                └──────────────────────────────────────────┘              │
│           Instance: botwok.local:3000 · v0.9.2 · local install           │
└──────────────────────────────────────────────────────────────────────────┘
```

#### Header
No shell; centered logo, theme toggle top-right.

#### Sidebar / navigation state
None.

#### Components
Card, Form (react-hook-form + zod), Input with correct `autocomplete`, Checkbox, Button, Alert.

#### Buttons & actions
`Sign in`; `(Forgot?)` swaps in a reset form that always answers "If an account exists, a link was sent"; `(Create one)` → `/signup`.

#### Tables / cards / filters
N/A.

#### Modals & drawers
None.

#### Empty state
N/A.

#### Loading state
Button spinner, inputs disabled; card Skeleton while `GET /api/v1/auth/me` resolves the redirect.

#### Error state
401 "Email or password is incorrect"; 429 with countdown; 5xx with `(Retry)`.

#### Mobile behavior
Full-width card, 16px gutters, 44px inputs.

#### Data it reads / writes
`POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `POST /api/v1/auth/password/reset`.

#### Transparency requirements
No AI. The footer names the instance being signed in to (local-first users may run several).

---

## 2. Signup

Route: `/signup`, `/signup?invite=[token]`.

#### Purpose
Create an account; with an invite token, join that workspace instead of creating one.

#### Layout
Centered Card as in Login; the invite banner and locked email appear only with a token.

```
┌──────────────────────────────────────────────┐
│ Create your account                ▣ Botwok  │
│ ⓘ Joining Acme Co as editor · from Jo Li     │
│ Full name  [ Sam Branch                    ] │
│ Email      [ sam@acme.com           locked ] │
│ Password   [ ••••••••••••             ◎    ] │
│            ▓▓▓▓▓▓░░ strong · 12+ chars       │
│ [Create account]      Have one? (Sign in)    │
└──────────────────────────────────────────────┘
```

#### Header
Logo only.

#### Sidebar / navigation state
None.

#### Components
Card, Form, Input, strength meter, Badge (invite role), Alert.

#### Buttons & actions
`Create account` → `/onboarding`, or with invite → accept invitation → `/w/[ws]/dashboard`.

#### Tables / cards / filters
N/A.

#### Modals & drawers
None.

#### Empty state
N/A.

#### Loading state
Button spinner; Skeleton line for the invite banner while the token is validated.

#### Error state
409 "Already registered (Sign in)"; invalid/expired invite → warning Alert, standalone signup still possible; field-level password errors.

#### Mobile behavior
As Login.

#### Data it reads / writes
`POST /api/v1/auth/signup`, `POST /api/v1/invitations/{token}/accept`, `GET /api/v1/auth/me`.

#### Transparency requirements
No AI. Workspace, inviter and role are shown before the account is created.

---

## 3. Onboarding

Route: `/onboarding?step=1…6`. Each step persists on Continue; returning resumes at the first incomplete step.

#### Purpose
Reach a workspace with one brand, a usable BrandContext, one connected account and goals. Steps 3–5 skippable.

#### Layout
Step 3 shown; other steps use the same frame.

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ ▣ Botwok                                                          (Exit to dashboard)   │
│ ① Workspace ─ ② Brand ─ ●③ Import ─ ④ Connect ─ ⑤ Goals ─ ⑥ Done                        │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ Import from your website                                                                │
│ We read public pages of acme.com and propose brand fields. Nothing is saved until you   │
│ accept it.                                                                              │
│ ┌───────────────────────────────────┐  ┌────────────────────────────────────────────┐   │
│ │ Progress                          │  │ Proposed fields                       ✦ AI │   │
│ │ ✓ Fetch pages (12 of 12)    6.2s  │  │ Description  "Specialty roaster…" ✓ ✎ ✕    │   │
│ │ ✓ Extract text & images     2.1s  │  │ Audience     "Home baristas 25–45" ✓ ✎ ✕   │   │
│ │ ⟳ Infer voice & tone        …     │  │ Tone         friendly · expert ✓ ✎ ✕       │   │
│ │ ○ Suggest content pillars         │  │ Pillars (4)  ▸ Brewing guides … ✓ ✎ ✕      │   │
│ │ ○ Detect competitors mentioned    │  │ Colors       ■ #3B2A20 ■ #E8D8C3  ✓ ✕      │   │
│ │ Cost so far $0.012                │  │ Competitors  ▸ 2 found ☐ add as tracked    │   │
│ │ ▸ Pages read (12)                 │  │ Each field: hover → source page + snippet  │   │
│ └───────────────────────────────────┘  └────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│ (Back)                                            (Skip this step)  [Accept & continue] │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

| Step | Content | Writes |
|---|---|---|
| ① Workspace | Name, slug (`/w/acme` preview), timezone (detected), language | `POST /api/v1/workspaces` |
| ② Brand basics | Name, website, industry, one-line description, language, optional logo | `POST /api/v1/brands`, `POST /api/v1/brands/{brandId}/assets` |
| ③ Import | Website import with per-field proposals | `POST /api/v1/brands/{brandId}/import-from-website`, then `PUT …/settings`, `POST …/pillars` for accepted fields |
| ④ Connect | Platform cards with requirement explainers (§20) | `GET /api/v1/social/connect/{platform}` → OAuth → `GET /api/v1/social/callback/{platform}` |
| ⑤ Goals | Goal cards, posts/week per platform, platform priority | `PUT /api/v1/brands/{brandId}/settings` |
| ⑥ Done | Setup checklist; `[Generate my first week of ideas]` (starts a run, opens §6), `(Go to dashboard)` | `POST /api/v1/ai/runs` |

#### Header
Logo, stepper, `(Exit to dashboard)` from step 3 (skipped steps become a Dashboard "Finish setup" card).

#### Sidebar / navigation state
No sidebar; stepper allows jumping back to completed steps only.

#### Components
Stepper, Card, Form, Combobox, selectable cards, Slider, progress checklist, Collapsible.

#### Buttons & actions
Continue, Back, Skip; step 3 per-field `✓` `✎` `✕` and `(Accept all)`.

#### Tables / cards / filters
Platform and goal cards.

#### Modals & drawers
OAuth popup (fallback redirect).

#### Empty state
Step 3, site unreadable: "Couldn't read acme.com — fill these later in Brand Settings." `(Try another URL)`.

#### Loading state
Step 3 checklist driven by SSE; proposals appear as each step finishes.

#### Error state
Failed import steps show `✗`, reason, `(Retry step)`; partial results remain acceptable. OAuth denial explained.

#### Mobile behavior
"Step 3 of 6" label instead of the stepper; panels stack; footer actions sticky.

#### Data it reads / writes
Routes in the step table, plus `GET /api/v1/auth/me` (resume).

#### Transparency requirements
Pages fetched, the agent behind each field (`research`, `strategy`, `competitor_intel`), source snippet per field, cost; nothing stored until accepted.

---

## 4. Workspace

Route: `/w/[ws]/overview` (from the workspace switcher).

#### Purpose
Workspace summary (brands, health, members, usage) plus switching and creating workspaces.

#### Layout
```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ Acme Co  ✎                                    (Workspace settings)  [+ New brand]       │
│ Owner: Sam Branch · 3 brands · 7 members · TZ Europe/Berlin                             │
├──────────────────────────────────────────────────────────┬──────────────────────────────┤
│ Brands                                                   │ Members           (Invite +) │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │ (SB) Sam      owner          │
│ │ ◆ Acme Coffee│ │ ◆ Acme Tea   │ │ ◆ Acme B2B   │       │ (JL) Jo Li    admin          │
│ │ li ig x  ●3  │ │ ig pi    ●1  │ │ li       ●0  │       │ (RK) Ravi K   approver       │
│ │ 4 pending ✓  │ │ 0 pending    │ │ 1 failed ✗   │       │ +4 more · (Manage team)      │
│ │ [Open]       │ │ [Open]       │ │ [Open]       │       ├──────────────────────────────┤
│ └──────────────┘ └──────────────┘ └──────────────┘       │ Usage this month             │
├──────────────────────────────────────────────────────────┤ AI   $31.20 / $100 ▓▓▓░░░░   │
│ Account health                                           │ Posts published   46         │
│ ● 9 active  ○ 1 expired  ○ 0 revoked  ● 1 error  (Fix →) │ Media storage  2.1 GB        │
├──────────────────────────────────────────────────────────┤ Runs 128 · failed 3          │
│ Your workspaces                                          │                              │
│ ▣ Acme Co (current) · ▣ Side Project · (+ Create)        │                              │
└──────────────────────────────────────────────────────────┴──────────────────────────────┘
```

#### Header
Workspace name (inline rename for owner/admin), `(Workspace settings)` → §24, `+ New brand`.

#### Sidebar / navigation state
No item active; breadcrumb "Workspace".

#### Components
Brand cards, Avatar list with role Badges, usage meters, health counts.

#### Buttons & actions
`+ New brand` (Dialog, then offers website import); `Open` sets the brand; `(Invite +)` → §23; `(Fix →)` → non-active accounts; `(+ Create)` workspace.

#### Tables / cards / filters
Brand cards: platforms, pending, failed.

#### Modals & drawers
New brand, Create workspace, Invite Dialogs.

#### Empty state
"No brands yet. A brand holds voice, pillars and connected accounts." `[+ New brand]`.

#### Loading state
Per-card Skeletons.

#### Error state
Per-card Alert with `(Retry)`.

#### Mobile behavior
Single column; brands as a horizontal carousel.

#### Data it reads / writes
`GET /api/v1/workspaces`, `GET/PATCH /api/v1/workspaces/{ws}`, `GET /api/v1/workspaces/{ws}/members`, `GET/POST /api/v1/brands`, `GET /api/v1/social/accounts`, `GET /api/v1/ai/usage`, `GET /api/v1/settings/budgets`.

#### Transparency requirements
Usage figures link to their detail screens.

---

## 5. Dashboard

Route: `/w/[ws]/dashboard`, scoped by the brand switcher.

#### Purpose
Daily start: what needs action, what goes out next, how content performs, what the AI recommends.

#### Layout
```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│ Dashboard · Acme Coffee            Period: Last 7 days ▾  vs prev ▾      (Customize)    │
├────────────────────┬────────────────────┬────────────────────┬──────────────────────────┤
│ Reach        48.2k │ Eng. rate    4.1%  │ Published     12   │ Followers (net)   +318   │
│ ▲ 12% vs prev      │ ▼ 0.3 pt           │ ▲ 2                │ ▲ 9%   ▁▂▃▅▆▇            │
├────────────────────┴────────────────────┴──────┬─────────────┴──────────────────────────┤
│ Needs your attention                       (6) │ Next 7 days               (Calendar →) │
│ ⏸ 4 posts awaiting your approval     [Review]  │ Today 09:00 li ● Scheduled "Q4 plan…"  │
│ ✗ 1 post failed · ig · token expired [Fix]     │ Today 13:30 ig ● Needs Review "Latte…" │
│ ⚠ li token expires in 3 days      [Reconnect]  │ Wed   10:00 x  ● Approved "Decaf…"     │
│ ⚠ AI budget at 82% this month         [View]   │ Thu   09:00 li ● Scheduled "Supplier…" │
│ ⏸ Automation "News→LinkedIn" waiting [Open]    │ (+ 3 more)                             │
├────────────────────────────────────────────────┼────────────────────────────────────────┤
│ ✦ AI insights & recommendations                │ Trending now              (Trends →)   │
│ • Carousels on ig get 2.3× saves vs single     │ ▇ Cold brew at home  92  ▁▃▅▇  4 src   │
│   image (n=18, 30d)    (Accept) (Dismiss) (?)  │ ▆ Decaf revival      78  ▁▂▄▅  7 src   │
│ • Post li Tue/Wed 08–10 (+31% eng.)            │ (Create ideas)                         │
├────────────────────────────────────────────────┼────────────────────────────────────────┤
│ Recently published                             │ Running now                            │
│ li "Supplier story"  2d  1.2k reach  5.3%  ↗   │ ⟳ Run "Weekly ideas" 3/5 $0.04 (Open)  │
│ ig "Pour-over 101"   3d  3.4k reach  6.1%  ↗   │ ⟳ Sync analytics · li ig  (Open)       │
└────────────────────────────────────────────────┴────────────────────────────────────────┘
```

#### Header
Title + brand, period Select, comparison Select, `(Customize)` (widget visibility per user).

#### Sidebar / navigation state
Dashboard active; mobile Home tab.

#### Components
KPI Cards (value, delta, sparkline), attention list, 7-day agenda, insight cards, trend list, running jobs.

#### Buttons & actions
Each attention row has one deep-linked fix. Insight `(Accept)` opens a prefilled proposal (never edits schedules directly); `(Dismiss)` takes a reason; `(?)` shows evidence. `(Create ideas)` → §11.

#### Tables / cards / filters
Widgets follow brand and period.

#### Modals & drawers
Insight evidence Sheet: metric table, sample posts, data window, platforms included.

#### Empty state
No accounts: KPIs "—" with `(Connect →)`; "Finish setup" checklist.

#### Loading state
Independent Skeleton per widget.

#### Error state
Per-widget Alert; stale analytics labelled with last sync.

#### Mobile behavior
Attention first, then agenda, KPIs 2×2, insights.

#### Data it reads / writes
`GET /api/v1/analytics/overview`, `GET /api/v1/calendar?from=&to=&view=list`, `GET /api/v1/approvals`, `GET /api/v1/publishing/queue`, `GET /api/v1/social/accounts`, `GET /api/v1/ai/usage`, `GET /api/v1/insights`, `GET/PATCH /api/v1/insights/recommendations/{id}`, `GET /api/v1/trends`, `GET /api/v1/ai/runs`, `GET /api/v1/automations`.

#### Transparency requirements
Insights show agent (`performance_analyst`), data window, sample size, excluded platforms, confidence and run link.

---

## 6. AI Assistant / Command Center

Route: `/w/[ws]/command-center` (new run), `/w/[ws]/command-center/[runId]`.

#### Purpose
Central AI interface. The `Orchestrator` (`IntentRouter` → `Planner` → `Executor`) plans and runs steps, returns content, and parks side-effect proposals at the `ApprovalGate`. Every step, source, tool call, cost and failure is inspectable; runs are paused, resumed or cancelled here.

#### Layout
Run detail, three resizable panes:

```
┌────────────────────┬─────────────────────────────────────────────────────────────────────────────┐
│ Runs   [+ New run] │ Run r_01J9…  "Plan next week of li posts from AI-in-retail news"            │
│ Brand ▾  By ▾      │ ⟳ running · step 3/6 · 00:42 · 18.2k tok · $0.087   (■ Cancel ⌘.)           │
├────────────────────┼──────────────────────────────────────────────┬──────────────────────────────┤
│ (Search runs…)     │ You  /plan next week of li posts from        │ ⏸ AWAITING APPROVAL (1)      │
│ Status ▾  Agent ▾  │      AI-in-retail news for @Acme Coffee      │ ┌──────────────────────────┐ │
│ ────────────────── │ ──────────────────────────────────────────── │ │ Schedule 5 posts         │ │
│ ⟳ LinkedIn week    │ ✓ Planning…  plan v1 · 6 steps      2.1s ▸   │ │ li · Mon–Fri 09:00 CET   │ │
│   2m · $0.09       │ ✓ 1 research  Find retail-AI news  14.3s ▸   │ │ publishing.propose_      │ │
│ ✓ Competitor rpt   │ ✓ 2 trend     Score 12 topics       3.0s ▸   │ │   schedule · step 6      │ │
│   1h · $0.31       │ ⟳ 3 ideation  Generate 10 ideas     8s… ▾    │ │ [Approve] (Reject) (View)│ │
│ ✗ Trend scan       │ ┌─────────────────────────────────────────┐  │ └──────────────────────────┘ │
│   Tue · $0.02      │ │ agent ideation · cheap → ollama/llama3.1│  │ ──────────────────────────── │
│ ⏸ IG carousel      │ │ Tool calls                              │  │ [Output 5] (Sources 14) (Why)│
│   Mon · awaiting   │ │  ✓ memory.search "pillars"       120ms  │  │ ☐ ✦ li "Most retailers…"     │
│ ⊘ Blog repurpose   │ │  ✓ research.list_sources  14 src  80ms  │  │  AI Generated · critic 82    │
│   Sep 30 · cancel  │ │  ⟳ LLM call  in 4.1k tok · out …        │  │  (Open in Studio) (Approve)  │
│ ▸ automation runs  │ │ Sources used 6 ▸  4.1k tok  $0.003      │  │  (Schedule) (Regen) (Discard)│
│                    │ │ (Raw I/O) (Retry step) (Copy ids)       │  │ ☐ ✦ li "3 ways stores use…"  │
│ (Load more)        │ └─────────────────────────────────────────┘  │  ⟳ critic running…           │
│                    │ ○ 4 writer    Draft 5 li posts               │ ☐ ✦ li "Inventory bots…"     │
│                    │ ○ 5 critic    Score + fact_check             │  ○ waiting for step 5        │
│                    │ ○ 6 propose   Schedule 5 posts     ⏸ gate    │ (Approve selected) (Export)  │
│                    │ ──────────────────────────────────────────── │                              │
│                    │ ┌ Follow up… /command @mention ──────────┐   │                              │
│                    │ └────────────────────────────── [Send ⌘↵]┘   │                              │
└────────────────────┴──────────────────────────────────────────────┴──────────────────────────────┘
```

Right-pane tabs and the failure block (pinned above the timeline when any step failed):

```
┌──────────────────────────────────┬───────────────────────────────┬───────────────────────────────┐
│ Sources (14)  Sort: relevance ▾  │ Reasoning summary   ✦ planner │ ✗ WHAT FAILED                 │
│ ★92 ● high  nrf.com      Oct 6   │ Goal: 5 li posts, Mon–Fri     │ Step 2 trend · tool web.fetch │
│   "Retailers pilot AI agents…"   │ Assumptions                   │ 3 of 12 URLs: 403 / timeout   │
│   steps 1, 4 · (Open) (Cite)     │ • audience = retail ops leads │ Impact: scored 9 of 12 topics │
│ ★88 ● med   reuters.com  Oct 5   │ • exclude paywalled sources   │ Auto-retried 2× · continued   │
│ ★61 ● low   blog.x.io    Sep 2   │ Decisions                     │ (Retry failed) (Skip) (Logs)  │
│   ⚠ older than date range        │ • dropped 2 topics: overlap w/│                               │
│ (Save all to Research)           │   last week (memory.search)   │ Step 5 critic · not run       │
│                                  │ Open questions (1) (Answer)   │ Reason: run cancelled         │
└──────────────────────────────────┴───────────────────────────────┴───────────────────────────────┘
```

New run (no `runId`): large composer with slash-command list, brand and per-run budget Selects, `Attach (+)`, the note "Side effects are always proposed for approval", `[Run ⌘↵]`, and templates.

#### Header
Editable title, run id, `run_status_t` Badge, step `i/n`, elapsed, tokens, cost, brand; `(■ Cancel)`, `(▶ Resume)` when `paused` (budget stop or approval wait), `⋯` Duplicate, Raw events, Save as automation (§19).

#### Sidebar / navigation state
Command Center active; sidebar collapses to the rail below 1600px; global AI drawer hidden (`⌘J` focuses the composer).

#### Components
- **Composer**: `/` opens slash commands, `@` opens mentions (brands, competitors, campaigns, social accounts, content), sent as `context.mentions[] {type, id}`. Slash commands pin the first step's agent: `/research` research · `/listen` social_listening · `/competitor` competitor_intel · `/trends` trend · `/plan` strategy · `/ideas` ideation · `/write` writer · `/repurpose` repurposer · `/visual` visual · `/critique` critic · `/factcheck` fact_check · `/analyze` performance_analyst · `/report` report. No command → `IntentRouter` decides.
- **Run timeline**: first row always `Planning…` (`⟳` until planned, then plan version and step count; re-plans add `plan v2` with diff). Step rows: `ai_tasks.status` glyph, agent, title, live duration; `⏸ gate` when awaiting approval; `⊘` + reason when skipped.
- **Step card**: agent, tier → model, template version, tool calls (`domain.verb`, args, latency, status), LLM calls (tokens, cost), sources used, output summary, `(Raw I/O)`, `(Retry step)`.
- **Actions panel** (pinned, amber when non-empty): one card per proposed side effect (e.g. `publishing.propose_schedule`, publish, send report, enable automation) with scope (platforms, accounts, count, times + timezone), proposing step, `[Approve]` `(Reject)` `(View)`; View lets items be unticked before approval.
- **Generated content** (`Output` tab): `✦` items with platform, status, critic score; per item `(Open in Studio)`, `(Approve)` (editors: `(Request approval)`), `(Schedule)` (approved only), `(Regenerate)` (instruction Popover), `(Discard)` (→ `archived`, undo). Bulk approve/export.
- **Sources**: relevance, credibility, domain, date, using steps, `(Open)`, `(Cite)`; stale/paywall/duplicate warnings.
- **Reasoning summary** (`Why`): planner-written goal, assumptions, decisions with evidence, open questions with `(Answer)` (triggers re-plan). Structured rationale only, not raw model reasoning.
- **What failed**: every failed step or tool call, including recovered ones — error, impact on output, retries, `(Retry failed)` `(Skip)` `(Logs)`.
- **Run history**: search; filters status, agent, brand, initiator (user/automation/schedule); cost per row.

#### Buttons & actions
| Action | Route |
|---|---|
| `Run ⌘↵` → navigates to the new run | `POST /api/v1/ai/runs` |
| Follow-up `Send` (planner may extend the plan) | `POST /api/v1/ai/conversations` + run messages |
| `■ Cancel` (confirm: completed steps and drafts are kept; pending actions withdrawn) | `POST /api/v1/ai/runs/{runId}/cancel` |
| `▶ Resume`, `Retry step` (`{retry_task_id}`) | `POST /api/v1/ai/runs/{runId}/resume` |
| Action `Approve` / `Reject` (reason required); approval resumes the run via `ApprovalService` | `POST /api/v1/approvals/{id}/approve`, `…/reject` |
| Item `Regenerate` / `Discard` | `POST /api/v1/content/{id}/generate`, `…/transition` |

Viewers are read-only; users without approval rights see "Needs approver" on action cards.

#### Tables / cards / filters
Sources sortable and filterable by step; Output by type/status.

#### Modals & drawers
Raw I/O Sheet (secrets redacted), action detail Sheet, source drawer, plan-diff Dialog.

#### Empty state
New-run composer, templates, and: "Runs plan their own steps. Anything that posts, schedules or changes settings waits for your approval."

#### Loading state
`queued` shows position; `⟳ Planning…` with elapsed time; steps appear with the plan; writer output streams.

#### Error state
`failed`: banner with failing step and `(Retry from failed step)`. `BUDGET_EXCEEDED` pauses the run with `(Raise cap & resume)` (admin/owner). Provider outage names the fallback model. SSE loss → poll steps every 5s.

#### Mobile behavior
Segmented `Timeline | Output | Actions | Sources | Why` (Actions auto-selected on `awaiting_approval`); history and step cards in Sheets.

#### Data it reads / writes
Routes in the table, plus `GET /api/v1/ai/runs`, `GET /api/v1/ai/runs/{runId}`, `GET /api/v1/ai/runs/{runId}/steps`, `GET /api/v1/ai/runs/{runId}/tool-calls`, `GET /api/v1/ai/conversations/{id}/messages`, `GET /api/v1/approvals`, `GET /api/v1/research/sources`, `POST /api/v1/content/{id}/request-approval`, `GET /api/v1/ai/usage`. SSE: `AI_RUN_*`, `BUDGET_THRESHOLD_REACHED`, `BUDGET_EXCEEDED`.

#### Transparency requirements
Reference implementation others link to (`run ↗`): plan and re-plans; per-step agent, model, template, tool calls, tokens, cost; every source and its use; reasoning summary; all failures and their impact; side effects kept separate from completed work and never executed without an `approvals` decision; cost vs budgets.

---

## 7. Research

Route: `/w/[ws]/research`, `/w/[ws]/research/[runId]`; tabs `Results | History | Feeds & keywords`.

#### Purpose
Run `research` agent jobs: find, rank, dedupe and summarize sources; save and cite them.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Research · Acme Coffee            [Results] (History) (Feeds & keywords)     [+ New run]         │
├──────────────────────────────┬───────────────────────────────────────────────────────────────────┤
│ NEW RUN                      │ "cold brew trends 2026" · ✓ completed · 38 sources · $0.09 (Run ▸)│
│ Query                        │ Sort: relevance ▾  Credibility ▾  Type ▾  ☐ Saved only  (Search…) │
│ [ cold brew trends 2026     ]│ ───────────────────────────────────────────────────────────────── │
│ Scope                        │ 1 ★94 ● high  nytimes.com · News · Oct 4             (Save) (Cite)│
│ ☑ Web  ☑ News  ☐ Social      │   Summary: cold brew retail sales up 18% YoY; growth at home…     │
│ ☑ Competitor sites  ☐ RSS    │   keywords: cold brew · RTD · at-home   used in 0 items           │
│ Depth ○ Quick ◉ Std ○ Deep   │ 2 ★90 ● high  sca.coffee · Web · Sep 28             ✓Saved (Cite) │
│ Dates [Last 30 days ▾]       │   Summary: survey of home brewing equipment ownership…            │
│ Brand [Acme Coffee ▾]        │ 3 ★72 ● med   reddit.com/r/coffee · Social · Oct 6  (Save) (Cite) │
│ Est. ~40 sources · ≤ $0.12   │   ⚠ user-generated content — verify before citing                 │
│ [Run research ⌘↵]            │ 4 ★65 ● med   brewbros.com/blog · Compet. · Oct 1   (Save) (Cite) │
│                              │ (Load 34 more)                    ✦ Summary of findings ▸         │
└──────────────────────────────┴───────────────────────────────────────────────────────────────────┘
```

#### Header
Title + brand, tabs, `+ New run` (focuses form).

#### Sidebar / navigation state
Research active; form collapses once a run starts (`(Edit query)` reopens).

#### Components
Form: query, scope (`web`, `news`, `social`, `competitor sites`, `rss`), depth, date range (Calendar Popover), brand. Rows: relevance `★`, credibility Badge, domain, type, date, summary, keywords. Cited "Summary of findings".

#### Buttons & actions
`Run research` (shows estimate), `(Save)`, `(Cite)` (→ `content_sources`), `(Run ▸)`, bulk Save/Cite.

#### Tables / cards / filters
Results sort/filter by relevance, date, credibility, type. **History** table: Query · Brand · Scope · Depth · Sources · Status · Cost · Date. **Feeds & keywords**: RSS feeds and tracked keywords with Add/Remove.

#### Modals & drawers
**Source detail drawer**: title, URL, published and retrieved dates, HTTP status, content hash, relevance/credibility reasons, keywords, topics, extracted content (cited passages highlighted), usages, `(Save)` `(Cite in…)` `(Open original ↗)`.

#### Empty state
"No research yet." plus three example queries built from brand pillars.

#### Loading state
Step checklist (search → fetch → dedupe → rank → summarize); results stream in.

#### Error state
Partial failures summarized ("6 URLs not fetched: 4 × 403"); run failure Alert with `(Retry)`.

#### Mobile behavior
Form in a bottom Sheet; result cards; drawer full-screen.

#### Data it reads / writes
`GET/POST /api/v1/research/runs`, `GET /api/v1/research/runs/{runId}`, `GET /api/v1/research/sources`, `GET /api/v1/research/sources/{id}`, `POST /api/v1/research/sources/{id}/save`, `GET/POST /api/v1/research/feeds`, `GET/POST /api/v1/research/keywords`. SSE: `RESEARCH_*`, `SOURCE_SAVED`.

#### Transparency requirements
Summary bullets must cite sources; per-source retrieval time, hash, robots/paywall flags, ranking reasons; merged duplicates listed; run cost and link.

---

## 8. Competitors

Route: `/w/[ws]/competitors`.

#### Purpose
Track competitors per brand: sync health, platforms, cadence; entry to detail and comparison.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Competitors · Acme Coffee  ▦ Grid ≡ List  Platform ▾ Sync ▾ Sort ▾  (Compare 2 ▸) [+ Competitor] │
├────────────────────────────────┬────────────────────────────────┬────────────────────────────────┤
│ ☑ Brew Bros                  ⋯ │ ☑ Bean There                 ⋯ │ ☐ Roast Lab                  ⋯ │
│ brewbros.com                   │ beanthere.co                   │ roastlab.io                    │
│ ig yt li tt    ✓ synced 2h     │ ig pi          ⟳ syncing 40%   │ li x           ✗ sync failed   │
│ Posts/wk ▁▃▅▃▆▅▇ 6.2           │ Posts/wk ▂▂▃▂▂▃▂ 2.1           │ Posts/wk —                     │
│ Followers 48k  ▲3% 30d         │ Followers 12k  ▲1% 30d         │ x: Not collected (platform     │
│ Official API · User-provided   │ Official API · Public web      │ restriction)                   │
│ [Open]                         │ [Open]                         │ (Retry sync) [Open]            │
└────────────────────────────────┴────────────────────────────────┴────────────────────────────────┘
```

#### Header
Title + brand, Grid/List toggle, filters, `(Compare n ▸)` (2–4 selected), `+ Competitor`.

#### Sidebar / navigation state
Competitors active.

#### Components
Cards/Table with selection, posting-frequency sparkline, sync Badge (`✓ synced` / `⟳ syncing n%` / `✗ sync failed`), data-availability badges.

#### Buttons & actions
`⋯` Sync now, Edit, Pause, Delete; `(Retry sync)`; Compare → §9.

#### Tables / cards / filters
List: Name · Platforms · Last sync · Posts/wk · Followers Δ30d · Data sources · Status. Filters: platform, sync status, data source.

#### Modals & drawers
**Add Competitor Dialog**: name, website, `(✦ Find handles from website)` (`competitor_intel`), a handle field per platform ("found on site" or "unverified"), tracking toggles (posts, website/blog, news), sync frequency, per-platform data-badge preview, `[Add & sync]`.

#### Empty state
"Track up to 10 competitors." `[+ Competitor]` `(✦ Suggest competitors)` (proposals only).

#### Loading state
Card Skeletons; new competitors show live sync progress.

#### Error state
Card-level failure with reason (e.g. "ig handle is not a professional account").

#### Mobile behavior
One card per row; compare limited to 2; Add as full Sheet.

#### Data it reads / writes
`GET/POST /api/v1/competitors`, `PATCH/DELETE /api/v1/competitors/{id}`, `POST /api/v1/competitors/{id}/sync`. SSE: `COMPETITOR_ADDED`, `COMPETITOR_UPDATED`, `COMPETITOR_SNAPSHOT_TAKEN`.

#### Transparency requirements
Data badges on every card; AI-suggested competitors and handles carry `✦` and the URL they came from.

---

## 9. Competitor Detail

Route: `/w/[ws]/competitors/[competitorId]?tab=`; comparison `/w/[ws]/competitors/compare?ids=`.

#### Purpose
One competitor in depth, every number labelled with its origin, plus gaps and opportunities.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ◀ Competitors / Brew Bros  brewbros.com ↗  ✓ synced 2h   (Sync now) (Compare ▸) (✦ Report)       │
├───────────────────────┬────────────────────────┬────────────────────────┬────────────────────────┤
│ ig  @brewbros         │ yt  Brew Bros TV       │ li  company/brewbros   │ tt  @brewbros          │
│ 48.2k followers       │ 9.1k subscribers       │ 5.3k followers         │ —                      │
│ 6.2 posts/wk          │ 0.5 videos/wk          │ 3.0 posts/wk           │ —                      │
│ ● Official API        │ ● Official API         │ ● User-provided        │ ○ Not collected        │
│                       │                        │                        │ (platform restriction) │
├───────────────────────┴────────────────────────┴────────────────────────┴────────────────────────┤
│ [Overview] Posts · Pillars & Hooks · Visual & Tone · Website & Blog · News · Gaps · Reports      │
├────────────────────────────────────────────────┬─────────────────────────────────────────────────┤
│ Posting frequency 90d     by platform ▾        │ You vs Brew Bros (30d)                          │
│ ▁▂▃▅▃▆▅▇▆▅▆▇   ig ━  li ┄                      │ Posts/wk       4.0   vs  6.2                    │
│ Formats  carousel 41% · video 33% · image 26%  │ Eng. rate      4.1%  vs  3.2%   (ig only)       │
│ ✦ Pillars  education 38% · product 30% · …     │ Top post  ig "Iced oat latte" 2.1k ↗            │
│ Best day/time  Tue 08:00 (ig, n=64)            │ li figures: User-provided, 2 snapshots          │
└────────────────────────────────────────────────┴─────────────────────────────────────────────────┘
```

#### Header
Breadcrumb, name, website, sync status, `(Sync now)`, `(Compare ▸)`, `(✦ Report)`.

#### Sidebar / navigation state
Competitors active.

#### Components
Profile card per platform (handle, audience, cadence, data badge). Tabs:
- **Overview**: cadence chart, format and pillar mix, best times, you-vs-them.
- **Posts**: grid/table of `competitor_posts` (thumbnail, platform, date, format, caption, engagement when collected, `↗`).
- **Pillars & Hooks** ✦: inferred pillars with share, hook patterns with example posts.
- **Visual & Tone** ✦: palettes, image styles, tone descriptors with quotes.
- **Website & Blog**: recent pages, topics, cadence. **News**: dated mentions.
- **Gaps & Opportunities** ✦: topics/formats they cover that you don't and vice versa, each with `(Create ideas)`.
- **Reports**: `competitor_reports` list, `(+ Generate)`.

**Comparison view**: columns = you + 1–4 competitors; rows = followers, posts/wk, format mix, top pillars, eng. rate; each cell carries its data badge; uncollected cells show `Not collected (platform restriction)`, never 0.

#### Buttons & actions
Sync now, Create ideas from a gap, Open original, ✦ Report, `⋯` Edit handles / Pause / Delete.

#### Tables / cards / filters
Posts filters: platform, format, date, min engagement. Snapshot date selector on Overview (`competitor_snapshots`).

#### Modals & drawers
Post detail Sheet (caption, media, metrics with collection time and badge); Generate report Dialog (period, sections).

#### Empty state
Restricted platforms: "Not collected for tt (platform restriction). (Add manually)".

#### Loading state
Skeletons; AI tabs show their snapshot date.

#### Error state
Per-platform errors in profile cards; analysis failures link to the run.

#### Mobile behavior
Profile cards scroll; tabs become a Select.

#### Data it reads / writes
`GET/PATCH/DELETE /api/v1/competitors/{id}`, `POST /api/v1/competitors/{id}/sync`, `GET /api/v1/competitors/{id}/posts`, `GET /api/v1/competitors/{id}/snapshots`, `GET /api/v1/competitors/compare?ids=`, `GET/POST /api/v1/competitors/{id}/reports`, `POST /api/v1/ideas/generate`.

#### Transparency requirements
Each metric shows data badge and collection time; AI tabs show `competitor_intel`, posts analyzed and evidence; nothing is imputed.

---

## 10. Trends

Route: `/w/[ws]/trends?trend=[id]`.

#### Purpose
Show trends from `TrendService` and the `trend` agent, scored for this brand, and turn them into ideas.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Trends · Acme Coffee  Window 7d ▾  Platform ▾  Source ▾  State ▾  Score ≥60 ▾  (Search) [⟳ Scan] │
├────────────────────────────────────────────────┬─────────────────────────────────────────────────┤
│ ▲ Cold brew at home         Score 92           │ ▲ Decaf revival             Score 78            │
│ Velocity ▁▂▃▅▇  +38%/wk  ● rising              │ Velocity ▁▂▂▄▅  +12%/wk  ● emerging             │
│ 14 sources · news 6 · web 5 · social 3         │ 7 sources · news 4 · social 3                   │
│ Platforms  ig tt pi                            │ Platforms  ig li                                │
│ Keywords cold brew · nitro · concentrate       │ Keywords decaf · swiss water · sleep            │
│ ✦ Fit high — pillar "Brewing guides"           │ ✦ Fit medium — no matching pillar               │
│ (Create ideas from trend) (Details) (✕)        │ (Create ideas from trend) (Details) (✕)         │
├────────────────────────────────────────────────┴─────────────────────────────────────────────────┤
│ Last scan 06:00 · 212 signals · 9 trends · next scan 18:00 (Automations)   Showing 2 of 9 ▸      │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Header
Title + brand; filters: window, platform, source type, state (emerging/rising/peaking/declining), min score; search; `[⟳ Scan]` with estimated cost.

#### Sidebar / navigation state
Trends active.

#### Components
Trend Card: label, score, velocity sparkline + %, state Badge, source counts by type, platforms, related keyword chips, ✦ brand-fit line.

#### Buttons & actions
`(Create ideas from trend)` → §11 prefilled; `(Details)`; `(✕)` dismiss (reason feeds scoring).

#### Tables / cards / filters
Table toggle: Trend · Score · Velocity · State · Sources · Platforms · First seen · Ideas created.

#### Modals & drawers
Trend drawer: score breakdown (volume, velocity, diversity, fit), signal timeline, `trend_signals` with links, ideas created.

#### Empty state
"No trends above 60 in 7 days. (Lower threshold) (Scan now)"; without keywords/feeds: "(Add keywords)".

#### Loading state
Skeleton cards; scan progress bar via SSE.

#### Error state
Per-source scan status (news ✓, web ✓, social ✗ rate-limited).

#### Mobile behavior
Stacked cards; filters in a Sheet; drawer full-screen.

#### Data it reads / writes
`GET /api/v1/trends`, `GET /api/v1/trends/{id}`, `POST /api/v1/trends/scan`, `POST /api/v1/ideas/generate`. SSE: `TREND_DETECTED`, `TREND_UPDATED`.

#### Transparency requirements
Score breakdown and signals always available; fit names the matched pillar; agent labels carry `✦`.

---

## 11. Content Ideas

Route: `/w/[ws]/ideas`.

#### Purpose
Collect, generate, triage and promote ideas into Studio.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Ideas · Acme Coffee  ▥ Board ≡ Table  Group Pillar ▾  Type ▾ Platform ▾ Source ▾ [✦ Generate] (+)│
├───────────────────────┬────────────────────────┬────────────────────────┬────────────────────────┤
│ EDUCATION (12)      ⋯ │ PRODUCT (7)         ⋯  │ COMMUNITY (5)       ⋯  │ ADVOCACY (3)        ⋯  │
│ ┌───────────────────┐ │ ┌───────────────────┐  │ ┌───────────────────┐  │ ┌───────────────────┐  │
│ │✦ 5 cold brew      │ │ │✦ Behind our decaf │  │ │  Latte art contest│  │ │✦ Why we pay 30%   │  │
│ │ mistakes          │ │ │ process           │  │ │ ugc · image · ig  │  │ │ above fair trade  │  │
│ │ educational       │ │ │ behind_the_scenes │  │ │ ★71 manual · Jo L.│  │ │ authority         │  │
│ │ carousel · ig pi  │ │ │ video · yt ig     │  │ │ → in Studio ↗     │  │ │ text · li         │  │
│ │ ★86 ↳ trend       │ │ │ ★79 ↳ research    │  │ └───────────────────┘  │ │ ★83 ↳ comp. gap   │  │
│ │ (Promote ▸)     ⋯ │ │ │ (Promote ▸)     ⋯ │  │                        │ │ (Promote ▸)     ⋯ │  │
│ └───────────────────┘ │ └───────────────────┘  │                        │ └───────────────────┘  │
│ (+ Idea)              │                        │                        │                        │
└───────────────────────┴────────────────────────┴────────────────────────┴────────────────────────┘
```

#### Header
Title + brand, Board/Table, group-by (pillar, platform, type, campaign), filters (type, platform, source), `[✦ Generate]`, `(+)` manual idea.

#### Sidebar / navigation state
Ideas active.

#### Components
Kanban columns (dragging between columns changes the grouped field), idea Card (title, `content_type_t`, `content_format_t`, platforms, score, source `↳`), Table.

#### Buttons & actions
`(Promote ▸)` creates a `draft` content item and opens Studio. `⋯` Edit, Duplicate, Delete; bulk Promote.

#### Tables / cards / filters
Table: Idea · Type · Format · Platforms · Pillar · Score · Source · Created by · Promoted.

#### Modals & drawers
**Generate Ideas Dialog**: count, campaign, pillars, platforms, goals, inputs (trends, saved research, insights, competitor gaps), skip near-duplicates, agent/tier/cost, `[Generate]`. Idea Sheet: angle, hook, evidence.

#### Empty state
"No ideas yet." `[✦ Generate ideas]` or "start from a trend (Trends →)".

#### Loading state
Skeleton cards in target columns, replaced as ideas stream in.

#### Error state
Failure toast with `(Details)`.

#### Mobile behavior
Column Select + list; swipe to promote.

#### Data it reads / writes
`GET/POST /api/v1/ideas`, `PATCH/DELETE /api/v1/ideas/{id}`, `POST /api/v1/ideas/generate`, `POST /api/v1/ideas/{id}/promote`, `GET /api/v1/brands/{brandId}/pillars`, `GET /api/v1/campaigns`.

#### Transparency requirements
Ideas show `✦`, inspiring source and run; cost shown before generating.

---

## 12. Content Studio

Route: `/w/[ws]/studio` (list), `/w/[ws]/studio/[contentId]?variant=[platform]&panel=[tab]`.

#### Purpose
Write, generate, repurpose, check, approve and schedule one piece of content: a master `content_items` row plus per-platform `content_variants`, with version history and evidence for every claim.

#### Layout
Desktop (≥1280px): navigator 240px · editor (flex) · panel 360px, all resizable.

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ◀ Studio / Q4 cold brew launch  ● Needs Review ▾  (SB)(JL)  (✦ Repurpose) (Request approval) ⋯   │
├─────────────────────┬────────────────────────────────────────────────┬───────────────────────────┤
│ MASTER              │ [Master] li  ig  x  th  (+)   ◉ Edit ○ Preview │ [✦ AI] Sources  SEO  Media│
│ ● Draft · v7        │ HOOK                                   62/150  │ Critic  Approval  Schedule│
│ Q4 cold brew launch │ Most Q4 plans fail in week one. Here is how    │ ──────────────────────────│
│ ─────────────────── │ three roasters avoided it.                     │ ✦ CRITIC  (variant li)    │
│ VARIANTS      (+)   │ BODY                               1,240/3,000 │ Quality      82 ▓▓▓▓▓▓▓▓░░│
│ li ● Needs Review   │ B  I  •  1.  ↗  @  {var}   (✦ Regenerate ▾)    │ Brand fit    ✓ 90         │
│ ig ● AI Generated   │ Cold brew demand rose 18% this year [1], and…  │ Platform     ✓ li rules   │
│ x  ● Draft  ⚠ 312   │ …                                              │ Policy risk  ✓ none found │
│ th ● Approved       │ CTA                                     38/150 │ FACT-CHECK (3 claims)     │
│ ─────────────────── │ Get the free brew guide → link in bio          │ ✓ "+18% demand" [1] nrf   │
│ VERSIONS            │ HASHTAGS  li 3 · recommended ≤ 5               │ ? "three roasters" no src │
│ v7 Sam · 2m         │ #coldbrew ✕  #coffee ✕  #retail ✕  (+)         │ ✗ "since 1990" vs [4]     │
│ v6 ✦ writer · 1h    │ ALT TEXT  ✓ 2 of 2 images described            │ SUGGESTIONS               │
│ v5 ✦ repurposer     │ MEDIA  [▣ 1] [▣ 2] (+ Add) (Carousel ▸)        │ • Cite claim 2     (Apply)│
│ (Compare ▸)         │ ────────────────────────────────────────────   │ • Remove claim 3   (Apply)│
│ ─────────────────── │ li 1,340/3,000 ✓  ig 1,340/2,200 ✓  x 312/280 ✗│ (Re-run) critic · balanced│
│ Campaign Q4 launch  │ ● Autosaved 5s · v7         (Discard) [Save ⌘S]│ $0.004 · run ↗            │
│ Pillar Brewing      │                                                │                           │
└─────────────────────┴────────────────────────────────────────────────┴───────────────────────────┘
```

Version compare (replaces the editor column):

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Compare  v5 ▾  ⇄  v7 ▾   ◉ Side by side ○ Inline   Variant li ▾      (Restore v5) (Close)        │
├────────────────────────────────────────────────┬─────────────────────────────────────────────────┤
│ v5 · ✦ repurposer · Oct 7 14:02                │ v7 · Sam · Oct 8 09:10                          │
│ Most Q4 plans [-fail-] in week one.            │ Most Q4 plans {+break+} in week one.            │
│ [-Three-] roasters avoided it.                 │ {+Here is how three+} roasters avoided it.      │
│ Hashtags #coldbrew #coffee                     │ Hashtags #coldbrew #coffee {+#retail+}          │
│ Media 1, 2                                     │ Media 1, 2                                      │
│ Critic 74                                      │ Critic 82 ▲                                     │
└────────────────────────────────────────────────┴─────────────────────────────────────────────────┘
```

Repurpose Dialog:

```
┌──────────────────────────────────────────────────────────────────┐
│ ✦ Repurpose "Q4 cold brew launch"                             ✕  │
│ Source  ◉ Master  ○ li variant                                   │
│ Target         Format         Constraints                        │
│ ☑ ig           carousel ▾     2,200 chars · 30 tags · ≤10 items  │
│ ☑ x            thread ▾       280 chars/post                     │
│ ☑ th           text ▾         500 chars                          │
│ ☐ tt           short_video    ⚠ needs a video asset              │
│ ☐ gbp          text           1,500 chars                        │
│ Keep ☑ sources ☑ CTA ☐ same media    Tone [Brand default ▾]      │
│ ⚠ ig variant exists: regenerated text becomes a new version      │
│ repurposer · balanced · est. $0.03          (Cancel) [Generate 3]│
└──────────────────────────────────────────────────────────────────┘
```

Mobile (stacked editor; panels open as bottom Sheets from the toolbar):

```
┌────────────────────────────────────┐
│ ◀ Q4 cold brew launch  ● Review ⋯  │
│ [Master] li ig x th (+)            │
│ HOOK                       62/150  │
│ Most Q4 plans fail in week one…    │
│ BODY                  1,240/3,000  │
│ Cold brew demand rose 18% [1]…     │
│ [▣][▣](+)  #coldbrew #coffee       │
├────────────────────────────────────┤
│ ✦AI  Src  Critic  Approve  Sched   │
│ (Preview)                  [Save]  │
└────────────────────────────────────┘
```

The list route is a Table (Title · Status · Platforms · Campaign · Owner · Updated) with `+ New post` (blank / from idea / ✦ from prompt).

#### Header
Editable title; status Badge menu with only valid transitions; presence avatars; `(✦ Repurpose)`; `(Request approval)` (approvers see Approve/Reject); `⋯` Duplicate, Export, AI runs, Archive.

#### Sidebar / navigation state
Studio active; sidebar collapses to the rail; the AI tab replaces the global drawer.

#### Components
**Navigator**: master (status, version); variants with status chip and limit warning (`⚠ 312`); `(+)` adds a platform; versions (`content_versions`, author user or `✦ agent`; pick two → Compare; Restore); campaign, pillar.

**Editor**: platform selector `[Master] li ig x th (+)`; each tab's tooltip lists the platform's constraints (characters, hashtag cap, media count/ratios, links, formats for the account type), supplied by the API with the variant. Sections **Hook**, **Body** (rich text, links, mentions, `{variables}`), **CTA**, each with a counter; per-platform totals ✓/✗. Hashtag chips (banned ones red). Alt text per image. Media strip with reorder and crop indicators. `◉ Edit ○ Preview` renders a platform-accurate mock (truncation, link card, carousel, x thread split). Citations `[n]` link to Sources. Autosave 5s; `⌘S` saves a version.

**Right panel tabs**

| Tab | Contents | Actions |
|---|---|---|
| ✦ AI Assistant | Write, Rewrite, Shorten, Expand, Change tone, Hook options, Translate; scope selection/section/variant/all; instruction box; output as inline diff | Apply, Apply to all, Discard |
| Research & Sources | Attached `content_sources` with claim ↔ source map, credibility, retrieved date; unsupported claims | Insert `[n]`, Attach, Remove |
| SEO / Hashtags | Keyword and hashtag suggestions with counts, platform caps, banned/restricted warnings, brand sets | Add, Add set |
| Media | Attached assets, per-platform crops, carousel builder, generate (§13), upload, library | Generate, Upload, Remove bg, Resize |
| Critic | Quality score; brand compliance; platform compliance; policy risks; per-claim fact-check (`✓` supported, `?` unverified, `✗` contradicted) with source; suggestions | Re-run, Apply |
| Approval | Status, approvers, due date, anchored comments, decision history by version | Request approval, Approve, Request changes, Reject |
| Schedule | Account per variant (expired → Reconnect), date/time + timezone, best-time chips ("Tue 08:30 · +24% · n=46"), recurrence | Schedule, Publish now, Add recurrence |

Schedule is disabled until the variant is `approved`; viewers are read-only.

#### Buttons & actions
- `(✦ Regenerate ▾)`: instruction, target section, keep sources, 1–3 options; results are suggestions until Apply.
- `(✦ Repurpose)`: format per target, missing requirements flagged; creates `ai_generated` variants; existing variants get a new version.
- `Restore` creates a new version.

#### Tables / cards / filters
Navigator filter "Show issues only".

#### Modals & drawers
Repurpose, Regenerate, Request approval, Generate image (§13), source drawer (§7), conflict Dialog.

#### Empty state
Placeholder sections; AI tab offers "Draft from a prompt", "Start from an idea".

#### Loading state
Editor Skeleton; generation overlays the section with "✦ writer is drafting… (Cancel)" and streams a suggestion.

#### Error state
Save failure keeps a local draft and retries. Conflict: "Jo saved v8" → View diff / Keep mine as v9 / Discard. Generation failure leaves text untouched. Constraint violations block Request approval.

#### Mobile behavior
Stacked editor; panel tabs open bottom Sheets; compare is inline-diff only.

#### Data it reads / writes
`GET/POST /api/v1/content`, `GET/PATCH/DELETE /api/v1/content/{id}`, `GET/POST /api/v1/content/{id}/variants`, `PATCH /api/v1/content/{id}/variants/{variantId}`, `GET /api/v1/content/{id}/versions`, `POST /api/v1/content/{id}/versions/{v}/restore`, `POST /api/v1/content/{id}/{generate,repurpose,critique,fact-check,transition,request-approval}`, `POST /api/v1/approvals/{id}/approve|reject`, `GET /api/v1/research/sources`, `GET /api/v1/research/keywords`, `POST /api/v1/media/{upload-url,generate}`, `POST /api/v1/media/{id}/transform`, `POST /api/v1/media/{id}/remove-background`, `GET /api/v1/social/accounts`, `POST /api/v1/scheduling/best-times`, `POST /api/v1/scheduling/posts`, `GET/POST /api/v1/scheduling/recurring`, `POST /api/v1/publishing/publish-now`.

#### Transparency requirements
Agent versions show `✦ agent`; applied suggestions log agent, model, run, cost. Claims link to sources; unsupported claims block approval when policy requires. Critic shows its model (≠ writer) and rules checked. Best-time chips state their basis. Repurpose lists what constraints changed. Nothing schedules without an approved variant and explicit user action.

---

## 13. Media Library

Route: `/w/[ws]/media?asset=[id]`.

#### Purpose
Store, find, generate and transform media, and see where each asset is used.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Media Library · Acme Coffee                         (✦ Generate image) (Upload) [+ Add]          │
├───────────────────────────────────────────────────────────────────┬──────────────────────────────┤
│ Type ▾  Brand ▾  Source ◉ All ○ Uploaded ○ ✦ Generated  (Search…) │ ✦ beans.png              ✕   │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │ Generated · Oct 7 · 1024²    │
│ │ ▣ image  │ │ ▶ 0:32   │ │ ▣ ✦      │ │ ▦ 6 sl.  │ │ ▣ logo   │  │ provider/model ▸ prompt ▸    │
│ │ 1080²    │ │ 9:16     │ │ 1024²    │ │ carousel │ │ svg      │  │ Alt [Roasted beans on…   ]   │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘  │ (✦ Suggest alt text)         │
│ latte.jpg    reel.mp4     beans.png    guide-car…   logo.svg      │ DERIVED FILES                │
│ used 3×      used 1×      unused       used 1×      brand asset   │ 1080×1350 ig 4:5      ⋯      │
│ ☐ select · (Bulk ▾)                            Showing 5 of 412   │ 1000×1500 pi 2:3      ⋯      │
│                                                                   │ beans-nobg.png        ⋯      │
│                                                                   │ USED IN "Q4 launch" li ↗     │
│                                                                   │ (Resize ▾) (Remove bg)       │
│                                                                   │ (Download) (Delete)          │
└───────────────────────────────────────────────────────────────────┴──────────────────────────────┘
```

#### Header
Title + brand, `(✦ Generate image)`, `(Upload)`, `+ Add` (upload, from URL, carousel).

#### Sidebar / navigation state
Media Library active.

#### Components
Asset grid (type, size, `✦`, usage), detail panel, page dropzone.

#### Buttons & actions
Alt text, `(✦ Suggest alt text)`, `(Resize ▾)` for platform presets (ig 4:5, 9:16; li 1.91:1; pi 2:3; yt 16:9) with focus point, `(Remove bg)`, `(Delete)` (blocked while scheduled).

#### Tables / cards / filters
Filters: type, brand, source (uploaded/generated), tag, used.

#### Modals & drawers
**Generate image Dialog**: provider/model (§22), platform size preset, style (brand default), prompt with `(✦ Write prompt from content)` (`visual`), negative prompt, reference images, count, cost; `Keep` saves `generated` assets.

#### Empty state
"Drop files here or generate an image."

#### Loading state
Skeleton tiles; processing tiles show progress until `MEDIA_PROCESSED`.

#### Error state
Per-tile error (codec, size, provider refusal reason).

#### Mobile behavior
3-column grid; detail Sheet.

#### Data it reads / writes
`GET/POST /api/v1/media`, `GET/DELETE /api/v1/media/{id}`, `POST /api/v1/media/upload-url`, `POST /api/v1/media/generate`, `POST /api/v1/media/{id}/transform`, `POST /api/v1/media/{id}/remove-background`. SSE: `MEDIA_GENERATED`, `MEDIA_PROCESSED`.

#### Transparency requirements
Generated assets keep provider, model, prompt, seed, cost; `✦` propagates to derived files and AI alt text.

---

## 14. Calendar

Route: `/w/[ws]/calendar?view=month|week|day|list|board&date=&tz=`.

#### Purpose
Plan and adjust timing across platforms with live status and limit checks.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Calendar  ◀ Oct 2026 ▶ (Today)  [Month] Week Day List Board  TZ Europe/Berlin ▾  Filters(3)▾ (+) │
├─────────────────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┤
│ UNSCHEDULED ✓ (4)   │ Mon 5    │ Tue 6    │ Wed 7    │ Thu 8    │ Fri 9    │ Sat 10   │ Sun 11   │
│ drag onto a day     │ li●09:00 │ ig●13:30 │          │ x ●10:00 │ li●09:00 │          │          │
│ ▣ x "Decaf myths"   │ Published│ Review   │          │ Approved │ Scheduled│          │          │
│   ● Approved        │          │ ig●08:00 │ ✦ idea   │          │ ig●12:00⚠│          │          │
│ ▣ ig "Latte art"    │          │ Failed ✗ │ Draft    │          │ Queued   │          │          │
│   ● Approved        │          │          │          │          │          │          │          │
│ (Show all)          │          │          │          │          │          │          │          │
├─────────────────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┤
│ ⚠ Fri 9 · ig @acmecoffee: 1 more post would exceed the Instagram API publish limit for 24h (View)│
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Header
Date navigation, `(Today)`, view switch, timezone Select (display; default workspace TZ), Filters, `(+)` quick-create.

#### Sidebar / navigation state
Calendar active; unscheduled tray is a collapsible in-page pane.

#### Components
Cards: platform, thumbnail, time, §0.5 status color; tray; limit banner.

#### Buttons & actions
| Card | Drag result |
|---|---|
| `scheduled`, `paused` | Optimistic move, `PATCH /api/v1/scheduling/posts/{id}` (`scheduled_at`), Undo toast |
| `queued` | Confirm Dialog: "Already queued for 09:00 — moving removes it from the queue." then PATCH |
| `publishing`, `published`, `failed`, `cancelled` | Not draggable (failed → Publishing) |
| No scheduled post (Idea…Approved with planned date) | Changes the planned date only |
| Tray item (approved, unscheduled) | Popover confirms account + time (best time prefilled) → `POST /api/v1/scheduling/posts` |

Week/day snap to 15 min. Drops into the past, onto non-`active` accounts or past a hard platform limit are rejected with the reason; soft limits warn. Empty slot click → quick-create (title, platforms, ☐ ✦ draft with AI). Card click → preview Sheet.

#### Tables / cards / filters
Filters: platform, status, campaign, pillar, team member, approval, scheduled/published. List = Table; Board = nine status columns.

#### Modals & drawers
Requeue confirm, tray Popover, preview Sheet.

#### Empty state
"Nothing planned for October." `(Open Ideas)` `(+ Quick create)`.

#### Loading state
Per-day Skeleton cards.

#### Error state
Failed moves roll back with the reason.

#### Mobile behavior
Agenda list default; `⋯ → Reschedule` replaces drag.

#### Data it reads / writes
`GET /api/v1/calendar?from=&to=&view=`, `GET/POST /api/v1/scheduling/posts`, `PATCH /api/v1/scheduling/posts/{id}`, `POST /api/v1/scheduling/posts/{id}/pause|resume|cancel`, `POST /api/v1/scheduling/best-times`, `PATCH /api/v1/content/{id}`. SSE: `POST_*`, `PUBLISH_*`.

#### Transparency requirements
Limit warnings name the limit and its source; AI-created cards show `✦`.

---

## 15. Approvals

Route: `/w/[ws]/approvals`, `/w/[ws]/approvals/[approvalId]`.

#### Purpose
Approver inbox with everything needed to decide, individually or in bulk.

#### Layout
```
┌─────────────────────────────────┬────────────────────────────────────────────────────────────────┐
│ Pending (6)  Mine ▾  Brand ▾    │ "Q4 cold brew launch" · li variant · v7      (Open in Studio ↗)│
│ ☐ Select all   (Bulk approve)   │ Requested by Sam · 2h ago · "Ready for Tue launch"             │
│ ◆ ACME COFFEE (4)               │ [li] ig  x  th    ◉ Preview ○ Text ○ Diff vs last approved     │
│ ☐ ● li "Q4 cold brew…"          │ ┌──────────────────────────────────────────────────────────┐   │
│   Sam · 2h · due today          │ │ (Acme Coffee) · 1st                                      │   │
│ ☐ ● ig "Latte art…"             │ │ Most Q4 plans fail in week one. Here is how three…       │   │
│   ✦ automation · 5h             │ │ [ image 1 / 2 ]                         …see more        │   │
│ ☐ ● x  "Decaf myths"            │ └──────────────────────────────────────────────────────────┘   │
│ ◆ ACME TEA (2)                  │ Critic 82 · brand 90 · platform ✓ · policy ✓                   │
│ ☐ ● pi "Matcha guide"           │ Fact-check 1 ✓ · 1 ? unverified · 1 ✗ contradicted  (View)     │
│ (Approval policies ↗)           │ Sources 3 ▸   ✦ writer + repurposer · 2 runs · $0.05 ▸         │
│                                 │ Comment [ Optional for approve, required otherwise      ]      │
│                                 │ [Approve ⌘↵]  (Request changes)  (Reject)        ◀ 1 of 6 ▶    │
└─────────────────────────────────┴────────────────────────────────────────────────────────────────┘
```

#### Header
Tabs `Pending | Decided | All`, Mine/All, brand filter, `(Approval policies ↗)` (§22).

#### Sidebar / navigation state
Approvals active with badge.

#### Components
Brand-grouped list; item preview per variant, critic, fact-check, sources, AI metadata, diff, comment.

#### Buttons & actions
`Approve`, `Request changes` (comment required; → `draft`), `Reject` (comment required; → `rejected`) — both via the reject route with `decision`. Bulk approve excludes warned items unless included. Approval resolves any waiting run gate.

#### Tables / cards / filters
Filters: brand, platform, requester, due.

#### Modals & drawers
Bulk approve Dialog, sources Sheet.

#### Empty state
"Nothing waiting for you."

#### Loading state
List and preview Skeletons.

#### Error state
409 names who decided; expired items offer `(Re-request)`.

#### Mobile behavior
Full-screen items with a sticky decision bar.

#### Data it reads / writes
`GET /api/v1/approvals`, `GET /api/v1/approvals/{id}`, `POST /api/v1/approvals/{id}/approve`, `POST /api/v1/approvals/{id}/reject`, `GET /api/v1/content/{id}`, `GET /api/v1/content/{id}/versions`, `GET /api/v1/ai/runs/{runId}`.

#### Transparency requirements
Agents, models, runs, cost; verdicts with sources, `?`/`✗` claims highlighted; the routing policy.

---

## 16. Publishing

Route: `/w/[ws]/publishing?status=&platform=`.

#### Purpose
Operational view of the `PublishingService` queue, failures, dead letters, platform health and rate limits.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Publishing   Queue [All ▾] Platform ▾ Account ▾ Brand ▾   (Search)          (Publish now ▸)      │
│ Health  li ● ok  ig ● ok  x ● rate-limited 12m  fb ● ok  tt ○ audit pending   (Details)          │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ ☐ Post                    Acct         When (CET)    Status        Att.  Next retry  Error       │
│ ☐ li "Q4 cold brew…"      Acme Coffee  Today 09:00   ● Scheduled   0/5   —           —           │
│ ☐ ig "Latte art…"         @acmecoffee  Today 13:30   ● Queued      0/5   —           —           │
│ ☐ x  "Decaf myths"        @acme        Today 14:00   ● Publishing  1/5   —           —           │
│ ☐ ig "Pour-over 101"      @acmecoffee  Today 08:00   ● Failed      3/5   in 4m       429 rate    │
│   ⋯ Retry now · Pause · Cancel · Edit in Studio · View attempts                                  │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ DEAD LETTER (2)  retries exhausted — needs a human                                               │
│ ig "Matcha guide"  @acmetea  Oct 6 10:00  5/5  OAuthException: token expired                     │
│   (Reconnect account) (Retry) (Edit) (Cancel)                                                    │
│ x "Weekend hours"   @acme     Oct 5 09:00  5/5  403 duplicate content                            │
│   (Retry) (Edit) (Cancel)                                                                        │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Header
Status filter (`scheduled`, `queued`, `publishing`, `failed`, `paused`, `cancelled`, `published` 24h), platform/account/brand, `(Publish now ▸)` (approved variants only).

#### Sidebar / navigation state
Publishing active; red dot when failures exist.

#### Components
Health strip (ok, degraded, rate-limited with reset time, audit pending), queue, dead letter.

#### Buttons & actions
Row: Retry, Pause/Resume, Cancel, Edit, Attempts. Dead letter: Retry, Edit, Cancel, contextual fix. Publish now confirms account and preview.

#### Tables / cards / filters
Post · Account · When · Status · Attempts n/max · Next retry · Error; published rows add the permalink.

#### Modals & drawers
Attempts Sheet (`publish_attempts`): time, HTTP status, platform error, idempotency key, reconciliation.

#### Empty state
"Queue is empty." Dead letter hidden when empty.

#### Loading state
Table Skeleton; status cells update via SSE.

#### Error state
Inline Alert.

#### Mobile behavior
Status-grouped cards.

#### Data it reads / writes
`GET /api/v1/publishing/queue`, `POST /api/v1/publishing/publish-now`, `GET /api/v1/publishing/attempts/{id}`, `POST /api/v1/publishing/attempts/{id}/retry`, `GET /api/v1/publishing/published`, `DELETE /api/v1/publishing/published/{id}` (typed confirm), `POST /api/v1/scheduling/posts/{id}/pause|resume|cancel`, `GET /api/v1/admin/health`. SSE: `PUBLISH_*`.

#### Transparency requirements
Raw platform error beside the message; reconciliation before risky retries; rows name the approving human — the LLM never publishes.

---

## 17. Analytics

Route: `/w/[ws]/analytics?period=&compare=&platform=`.

#### Purpose
Normalized cross-platform performance with comparisons, breakdowns, top posts, growth and AI insights.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Analytics · Acme Coffee  Last 30 days ▾ vs prev ▾  Platform ▾ Campaign ▾  (Sync now) (Export ▾)  │
├───────────────────────┬────────────────────────┬────────────────────────┬────────────────────────┤
│ Impressions  212k     │ Engagements  9.8k      │ Eng. rate    4.6%      │ Followers   +1.2k      │
│ ▲ 14%  ▁▂▃▅▆▇         │ ▲ 9%   ▁▃▃▅▅▆          │ ▼ 0.2 pt               │ ▲ 6%  (li ig yt)       │
├───────────────────────┴────────────────────────┼────────────────────────┴────────────────────────┤
│ Engagement over time     ◉ day ○ week          │ By platform (eng. rate)                         │
│ ▁▂▂▃▅▃▄▆▅▇▆▅▆▇  ━ this ┄ prev                  │ li ▓▓▓▓▓▓▓▓ 5.3%   ig ▓▓▓▓▓▓ 4.1%               │
│                                                │ x  ▓▓▓ 1.9%   th  n/a ⓘ                         │
├────────────────────────────────────────────────┼─────────────────────────────────────────────────┤
│ By pillar · By format   [tabs]                 │ Best hours (heatmap, eng. rate)                 │
│ Education ▓▓▓▓▓▓▓ 5.9%  carousel ▓▓▓▓▓▓ 6.1%   │      06  09  12  15  18  21                     │
│ Product   ▓▓▓▓ 3.8%     video    ▓▓▓▓ 4.0%     │ Mon  ░░  ▓▓  ▒▒  ░░  ▒▒  ░░                     │
│                                                │ Tue  ░░  ██  ▓▓  ░░  ▒▒  ░░                     │
├────────────────────────────────────────────────┴─────────────────────────────────────────────────┤
│ ⓘ Normalized metrics: not all platforms expose all metrics. n/a = not provided, not zero.        │
│ TOP POSTS  Post · Platform · Published · Impr. · Eng. · Eng. rate · Saves · Clicks · ✦ Why       │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Header
Period, comparison, platform/account/campaign filters, `(Sync now)`, `(Export ▾)` (CSV of view, chart PNG, or "Create report" → §18).

#### Sidebar / navigation state
Analytics active.

#### Components
KPIs; engagement over time; by platform, pillar, format; hour × day heatmap; top posts; growth; ✦ insights.

#### Buttons & actions
Chart clicks filter top posts; `(✦ Analyze)` runs `performance_analyst`; insight Accept/Dismiss.

#### Tables / cards / filters
Top posts and account growth Tables, sortable.

#### Modals & drawers
Post Sheet; metric definition Popover.

#### Empty state
"No metrics yet." `(Sync now)`.

#### Loading state
Chart Skeletons.

#### Error state
Per-account sync failures with fix links.

#### Mobile behavior
KPIs 2×2, charts stacked.

#### Data it reads / writes
`GET /api/v1/analytics/overview`, `GET /api/v1/analytics/posts`, `GET /api/v1/analytics/accounts`, `GET /api/v1/analytics/breakdown?by=`, `POST /api/v1/analytics/sync`, `GET /api/v1/insights`, `POST /api/v1/insights/analyze`, `GET/PATCH /api/v1/insights/recommendations/{id}`.

#### Transparency requirements
Persistent "not all platforms expose all metrics" note; `n/a` is never 0. Insights show window, sample, excluded platforms, run.

---

## 18. Reports

Route: `/w/[ws]/reports`, `/w/[ws]/reports/[reportId]`.

#### Purpose
Generate, schedule, read, export and deliver reports composed by the `report` agent from stored data.

#### Layout
```
┌────────────────────────┬─────────────────────────────────────────────────────────────────────────┐
│ REPORTS   [+ Generate] │ Weekly performance · Acme Coffee · Sep 29–Oct 5      ✦ report           │
│ Type ▾  Brand ▾        │ Generated Oct 6 08:02 · 3 sections · 11 sources · $0.06 (run ↗)         │
│ ● Weekly perf · Oct 6  │ (Export PDF) (Export Markdown) (Send ▾) (Regenerate) (Schedule)         │
│ ● Competitor · Sep 30  │ ────────────────────────────────────────────────────────────────────────│
│ ⟳ Campaign Q4 · running│ 1 Summary            ✦  Reach +12%, carousels led engagement [1][2]     │
│ ✗ Custom · failed      │ 2 Top posts          table · data: analytics snapshot Oct 6 06:00       │
│ SCHEDULED (2)          │ 3 Competitors        ✦  Brew Bros doubled tt cadence [3]                │
│ Weekly perf · Mon 08:00│ 4 Recommendations    ✦  3 items · (Send to Calendar ▸)                  │
│ → email, #marketing    │ Sources  [1] analytics: li posts … [2] ig posts … [3] competitor sync   │
└────────────────────────┴─────────────────────────────────────────────────────────────────────────┘
```

#### Header
Filters, `[+ Generate]`; viewer actions as wireframed.

#### Sidebar / navigation state
Reports active.

#### Components
Report and schedule lists; viewer with numbered sections, data tables, citations, Sources footer.

#### Buttons & actions
Export PDF/Markdown; `Send ▾` (email, Slack; confirm lists recipients); Regenerate (new version); Schedule.

#### Tables / cards / filters
Filters: type, brand, status.

#### Modals & drawers
**Generate wizard** (Dialog): ① type — weekly performance / competitor / campaign / custom (custom adds section picker and brief); ② period, brands, platforms, campaigns or competitors; ③ recipients — users, emails, Slack channel, format (PDF, Markdown, link); ④ schedule — once or recurring with timezone. Final step shows estimated cost and data freshness.

#### Empty state
The four report types as cards.

#### Loading state
Section checklist via SSE.

#### Error state
Failing section with `(Retry)`; per-recipient `(Resend)`.

#### Mobile behavior
Full-screen viewer; wizard as Sheet.

#### Data it reads / writes
`GET/POST /api/v1/reports`, `GET /api/v1/reports/{id}`, `GET /api/v1/reports/{id}/export?format=`, `GET/POST /api/v1/competitors/{id}/reports`. SSE: `REPORT_GENERATED`.

#### Transparency requirements
`✦` sections cite data or sources; tables state snapshot time; header shows agent, run, cost, freshness; external delivery is always confirmed.

---

## 19. Automations

Route: `/w/[ws]/automations`, `/w/[ws]/automations/[workflowId]?tab=runs&run=`.

#### Purpose
Build and operate no-code workflows run by `AutomationEngine`, which calls agents as nodes and halts at approval nodes.

#### Layout
List: Table — Name · Trigger · Enabled · Last run (glyph + time) · Next run · Success rate 30d · Owner; `+ New automation` (blank or template). Builder, showing the reference workflow:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ◀ Automations / News → LinkedIn   ● Enabled   v4 saved 2m   (Test run) (Runs) (Save) [Disable]   │
├───────────────┬───────────────────────────────────────────────────────┬──────────────────────────┤
│ NODES         │ ↯ WHEN new industry news detected  (rss: 3 feeds)     │ ◇ Condition         ✕    │
│ ↯ Trigger     │        │                                              │ Name [relevance gate]    │
│ ◇ Condition   │ ◇ IF relevance > 80 ──── no ───▶ ⊘ end                │ Field [trigger.relevance]│
│ ✦ AI Agent    │        │ yes                                          │ Operator [ > ▾ ]         │
│ ⌕ Research    │ ⌕ Research: deepen story · research agent             │ Value    [ 80 ]          │
│ ✎ Generate    │        │                                              │ No branch → [end ▾]      │
│ ⇄ Transform   │ ✦ Ideas ×3 · ideation · pick top 1                    │ ───────────────────────  │
│ ✓ Approve     │        │                                              │ TEST                     │
│ ◷ Schedule    │ ✎ Generate LinkedIn post · writer → critic            │ Use last event ▸         │
│ ➤ Publish     │        │                                              │ Result 86 → yes ✓        │
│ ⧗ Wait        │ ✓ Approval · role approver · expires 24h              │ (Test node)              │
│ ⇢ Webhook     │        │                                              │                          │
│ ◔ Notification│ ◷ Schedule · next best time on li                     │                          │
│ ▤ Analytics   │ (+ drop node)       zoom ⊖ ⊕  fit ⤢                   │                          │
│ ⚙ Action      │                                                       │                          │
└───────────────┴───────────────────────────────────────────────────────┴──────────────────────────┘
```

#### Header
Name, enabled state, version, Test run, Runs, Save, Enable/Disable (owner/admin).

#### Sidebar / navigation state
Automations active.

#### Components
Node palette (Trigger, Condition, AI Agent, Research, Generate, Transform, Approve, Schedule, Publish, Wait, Webhook, Notification, Analytics, Action; schemas from `node-types`), pan/zoom canvas with labelled branches and minimap, `⚠` on invalid nodes, config side panel generated from the node schema with an expression picker for upstream outputs (`trigger.relevance`).

#### Buttons & actions
`Test run` (last real event, sample, or JSON; Schedule/Publish/Webhook nodes are simulated and labelled "dry run"); `Test node`; `Save` (new version); `Enable` validates one trigger, no orphans, and an Approve node on every Publish path unless the workspace auto-approve policy (§22) covers it; Duplicate; Delete.

#### Tables / cards / filters
**Run history**: Run · Trigger event · Status (`running/waiting/awaiting_approval/succeeded/failed/cancelled`) · Started · Duration · Cost. Selecting a run overlays ✓ ⟳ ⏸ ✗ on nodes and opens per-step logs (input, output, linked `ai_runs`, errors, retries); `(Cancel run)` while active.

#### Modals & drawers
Templates, Test run Dialog, step log Sheet, version history.

#### Empty state
Templates, e.g. "News → LinkedIn post (with approval)".

#### Loading state
Canvas Skeleton; live run overlay via SSE.

#### Error state
Validation bar with jump-to-node; failed node red with `(Retry from node)`.

#### Mobile behavior
Builder read-only; list, runs, enable and cancel usable.

#### Data it reads / writes
`GET/POST /api/v1/automations`, `GET/PUT/DELETE /api/v1/automations/{id}`, `POST /api/v1/automations/{id}/enable|disable|run`, `GET /api/v1/automations/{id}/runs`, `GET /api/v1/automations/runs/{runId}`, `POST /api/v1/automations/runs/{runId}/cancel`, `GET /api/v1/automations/node-types`. SSE: `AUTOMATION_*`.

#### Transparency requirements
Runs show trigger, node inputs/outputs, linked AI runs and cost, approval waits, simulated vs real side effects; side-effect nodes are marked with their Approve guard.

---

## 20. Social Accounts

Route: `/w/[ws]/settings/social-accounts`.

#### Purpose
Connect, monitor, reconnect and disconnect accounts, and show what each account can do.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Social Accounts · Acme Coffee                               Status ▾  Platform ▾   [+ Connect]   │
├────────────────────────────────────────────────┬─────────────────────────────────────────────────┤
│ li  Acme Coffee · Organization  ● active       │ ig  @acmecoffee · Business      ○ expired       │
│ Token: 41 days left  ▓▓▓▓▓▓▓░░                 │ Token expired 2d ago · 3 posts at risk          │
│ Scopes w_organization_social,                  │ Scopes instagram_basic,                         │
│   r_organization_social (2 more ▸)             │   instagram_content_publish (+2 ▸)              │
│ CAN  text ✓ image ✓ video ✓ document ✓         │ CAN  image ✓ carousel ✓ reels ✓ story ✓         │
│ poll ✗ analytics ✓ native schedule ✗           │ text-only ✗ analytics ✓                         │
│ (Test) (Reconnect) (Disconnect)                │ [Reconnect]  (Disconnect)                       │
├────────────────────────────────────────────────┴─────────────────────────────────────────────────┤
│ CONNECT   (fb Page) (ig) (th) (li) (x) (tt) (yt) (pi) (gbp)    → each opens a requirements check │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Header
Status (`active/expired/revoked/error/disconnected`) and platform filters, `[+ Connect]` (owner/admin).

#### Sidebar / navigation state
Settings ▸ Social Accounts active.

#### Components
Account Card: platform, avatar, account type, status, token expiry countdown (amber < 7 days), scopes, capabilities matrix, dependent posts.

#### Buttons & actions
`Connect` → requirements Dialog → OAuth; `Test`; `Reconnect` (same account; scheduled posts keep it); `Disconnect` (Dialog: "3 scheduled posts will be paused", typed confirm).

#### Tables / cards / filters
Pre-connect requirements:

| Platform | Requirement shown |
|---|---|
| `facebook` | Admin of a Facebook Page |
| `instagram` | Professional (Business/Creator) account linked to a Facebook Page |
| `threads` | Threads profile |
| `linkedin` | Member profile, or Organization page admin (org posting needs an approved app) |
| `x` | X account; volume depends on the instance's API tier |
| `tiktok` | Creator/Business account; direct posting requires app audit — until then posts are restricted (e.g. private) |
| `youtube` | Channel owner/manager; uploads use API quota |
| `pinterest` | Business account |
| `gbp` | Location owner/manager; instance needs approved API access |

#### Modals & drawers
Requirements Dialog (checklist, plain-language scopes), OAuth popup, Disconnect Dialog, detail Sheet.

#### Empty state
Platform grid with Connect buttons.

#### Loading state
Card Skeletons.

#### Error state
OAuth errors show the platform message plus guidance.

#### Mobile behavior
Stacked cards; OAuth by redirect.

#### Data it reads / writes
`GET /api/v1/social/accounts`, `GET /api/v1/social/connect/{platform}`, `GET /api/v1/social/callback/{platform}`, `DELETE /api/v1/social/accounts/{id}`, `POST /api/v1/social/accounts/{id}/refresh`, `POST /api/v1/social/accounts/{id}/test`. SSE: `SOCIAL_ACCOUNT_*`.

#### Transparency requirements
Scopes in plain language next to technical names; the capability matrix reflects what the platform allows for this account type, and unsupported actions elsewhere link back here.

---

## 21. Brand Settings

Route: `/w/[ws]/settings/brand?tab=`.

#### Purpose
Edit the brand data `BrandService` compiles into the BrandContext every agent receives, and show that context.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Brand Settings · Acme Coffee   (✦ Import from website) (✦ Learn from my past posts)   [Save]     │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Profile Audience [Voice & Style] Visual Pillars Keywords·Hashtags·CTAs Goals Competitors         │
├────────────────────────────────────────────────────┬─────────────────────────────────────────────┤
│ Tone                 (✦ Learn from my past posts)  │ BRANDCONTEXT PREVIEW  v12  (Copy JSON)      │
│ Casual ├──────●──────┤ Formal                      │ {                                           │
│ Playful ├────●────────┤ Serious                    │  "brand": "Acme Coffee",                    │
│ Concise ├───●─────────┤ Detailed                   │  "voice": {"formality": 0.6, …},            │
│ Writing samples (3)  (+ Add) (✦ From posts)        │  "pillars": [ 4 items ],                    │
│ Vocabulary  use: brew, roast · avoid: cheap        │  "forbidden_topics": [ … ],                 │
│ Forbidden topics  politics · health claims         │  "audience": "home baristas 25–45",         │
│ Preferred topics  sourcing · home brewing          │ }  ≈ 1.8k tokens · sent to all agents       │
│ Emoji ◉ sparing ○ none ○ frequent                  │  ✦ fields marked: from website import       │
└────────────────────────────────────────────────────┴─────────────────────────────────────────────┘
```

#### Header
`(✦ Import from website)`, `(✦ Learn from my past posts)`, `[Save]` (owner/admin).

#### Sidebar / navigation state
Settings ▸ Brand active.

#### Components
Tabs: **Profile**; **Audience** (segments, pains, goals); **Voice & Style** (tone sliders, writing samples, vocabulary use/avoid, forbidden and preferred topics, emoji/formatting rules); **Visual Identity** (logos, colors with roles, fonts, image style); **Content Pillars** (description, target share, examples; reorder); **Keywords & Hashtags & CTAs** (keywords, per-platform hashtag sets, banned hashtags, CTA library); **Goals** (KPIs, posts/week per platform); **Competitors** (link to §8). Right pane: BrandContext preview (JSON, token estimate, version, changed fields).

#### Buttons & actions
Import/Learn return per-field proposals (Accept/Edit/Reject); Save versions `brand_settings`.

#### Tables / cards / filters
Pillars: Pillar · Target % · Actual % (30d) · Posts.

#### Modals & drawers
Proposal Sheet, version diff.

#### Empty state
Hint + Import action.

#### Loading state
Tab Skeletons; proposals stream in.

#### Error state
Field validation; run failure banner.

#### Mobile behavior
Tabs as Select.

#### Data it reads / writes
`GET/PATCH /api/v1/brands/{brandId}`, `GET/PUT /api/v1/brands/{brandId}/settings`, `GET/POST /api/v1/brands/{brandId}/pillars`, `POST /api/v1/brands/{brandId}/assets`, `POST /api/v1/brands/{brandId}/import-from-website`, `POST /api/v1/ai/runs`.

#### Transparency requirements
The preview uses the same serializer agents receive, with token size; AI-proposed fields keep `✦` and their source posts/pages until edited.

---

## 22. AI Settings

Route: `/w/[ws]/settings/ai?tab=providers|budgets|approvals|prompts|safety`.

#### Purpose
Providers, routing, local models, budgets, approval thresholds, prompt templates and safety. Owner/admin edit; others read.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ AI Settings   [Providers & routing] Budgets  Approvals  Prompts  Safety                  [Save]  │
├────────────────────────────────────────────────┬─────────────────────────────────────────────────┤
│ PROVIDER KEYS                                  │ MODEL ROUTING (per tier)                        │
│ LLM provider A   ● valid    (Rotate)           │ cheap     provider A · model-s   $/1M 0.2       │
│ LLM provider B   ○ not set  (Add key)          │ balanced  provider B · model-m   $/1M 3.0       │
│ Image provider   ● valid                       │ powerful  provider A · model-l   $/1M 15        │
│ Search provider  ⚠ quota 92%                   │ fallback  ☑ on provider error → next tier       │
│ Ollama  ● localhost:11434                      │ AGENT OVERRIDES                                 │
│   detected: llama3.1:8b, qwen2.5:14b           │ critic   → provider B · model-m (≠ writer)      │
│ Embeddings [provider A ▾]  Video [—▾]          │ ideation → ollama/llama3.1:8b (local)           │
└────────────────────────────────────────────────┴─────────────────────────────────────────────────┘
```

#### Header
Tabs, `[Save]` per tab with unsaved-changes guard.

#### Sidebar / navigation state
Settings ▸ AI active.

#### Components
- **Providers & routing**: write-only keys (last 4 shown, status); tier table for `cheap`, `balanced`, `powerful` (provider, model, price, context); fallback toggle; per-agent overrides for all 13 agents ("critic must differ from writer"); embedding, image, video, search provider Selects; Ollama endpoint, status and detected models.
- **Budgets**: monthly workspace budget, per-run cap, per-brand caps, alert thresholds, behavior at 100%; usage by agent/model.
- **Approvals**: auto-approve `never` (default) or `critic score ≥ X` plus required conditions (no ✗ fact-check, no policy risk), per platform; expiry; default approvers.
- **Prompts**: per-agent template editor with variables panel, version history with diff/restore, `Test` (dry run showing output, tokens, cost).
- **Safety**: require sources for factual claims, block publish on ✗ fact-check, PII redaction, competitor site fetching (robots.txt always respected), max autonomous steps per run.

#### Buttons & actions
Add/Rotate key, Test provider, Refresh models, Test template, Save.

#### Tables / cards / filters
Usage: Agent · Runs · Tokens · Cost · Avg/run · Failures, by period.

#### Modals & drawers
Add key, prompt diff, test result.

#### Empty state
"AI features are off until a provider key or local model is configured."

#### Loading state
Row Skeletons.

#### Error state
Provider errors inline; unmapped tiers block Save.

#### Mobile behavior
Read-only summaries; editing is desktop-only.

#### Data it reads / writes
`GET/PUT /api/v1/ai/settings`, `GET /api/v1/ai/agents`, `GET /api/v1/ai/usage`, `GET/PUT /api/v1/ai/prompts/{agentId}`, `GET/PUT /api/v1/settings/budgets`, `POST /api/v1/ai/runs` (dry run).

#### Transparency requirements
Show the model each agent will actually use after overrides and fallbacks, the prices behind cost figures, and "last changed by" per section (audit-logged).

---

## 23. Team

Route: `/w/[ws]/settings/team?tab=members|invitations|roles|activity`.

#### Purpose
Manage members, roles and invitations; review activity.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Team · Acme Co      [Members] Invitations (2)  Roles  Activity          (Search)  [+ Invite]     │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Member                 Email               Role          Brands       Last active                │
│ (SB) Sam Branch        sam@…               owner         all          now           ⋯            │
│ (JL) Jo Li             jo@…                admin ▾       all          2h            ⋯            │
│ (RK) Ravi K            ravi@…              approver ▾    Acme Coffee  1d            ⋯            │
│ (MT) Mia T             mia@…               editor ▾      all          5d            ⋯            │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Header
Tabs, search, `[+ Invite]` (owner/admin).

#### Sidebar / navigation state
Settings ▸ Team active.

#### Components
Members with role Select (only owners grant owner), invitations, roles (§4 matrix), activity feed.

#### Buttons & actions
Invite Dialog (emails, role `admin/editor/approver/viewer`, brand access, message); row Change role / Limit brands / Remove; invitation Resend / Revoke / Copy link; Transfer ownership (owner, typed confirm).

#### Tables / cards / filters
Filters: role, brand, last active.

#### Modals & drawers
Invite, Remove, Transfer Dialogs.

#### Empty state
"Invite teammates to review and approve content."

#### Loading state
Table Skeleton.

#### Error state
Per-email errors; last owner protected.

#### Mobile behavior
Member cards; invite as Sheet.

#### Data it reads / writes
`GET/POST /api/v1/workspaces/{ws}/members`, `PATCH/DELETE /api/v1/workspaces/{ws}/members/{userId}`, `POST /api/v1/workspaces/{ws}/invitations`; invitation list/revoke and activity need new routes (Appendix).

#### Transparency requirements
Activity labels automated actions "AI (run r_…) on behalf of Sam".

---

## 24. System Settings

Route: `/w/[ws]/settings/system?section=`; Admin / Debug `/w/[ws]/admin?tab=jobs|events|costs|health`.

#### Purpose
Workspace-wide configuration and the entry to Admin / Debug.

#### Layout
```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ System Settings · Acme Co                                                               [Save]   │
├───────────────────┬──────────────────────────────────────────────────────────────────────────────┤
│ General           │ NOTIFICATIONS                                                                │
│ Notifications     │ Event                     In-app  Email  Slack  Webhook                      │
│ Timezone & locale │ Approval requested        ☑       ☑      ☑      ☐                            │
│ Data retention    │ Publish failed            ☑       ☑      ☑      ☑                            │
│ Export & backup   │ Token expiring            ☑       ☑      ☐      ☐                            │
│ API keys          │ Budget threshold          ☑       ☑      ☐      ☐                            │
│ Danger zone       │ Channels  Email ● smtp ok · Slack ● #marketing · Webhook ○ (Add)             │
│ ────────────────  │                                                                              │
│ Admin / Debug ↗   │                                                                              │
└───────────────────┴──────────────────────────────────────────────────────────────────────────────┘
```

#### Header
`[Save]` per section.

#### Sidebar / navigation state
Settings ▸ System active; in-page section nav.

#### Components
**General** (name, slug, logo, language); **Notifications** (event × channel matrix; email SMTP status, Slack workspace/channel, webhooks with secret and `Send test`); **Timezone & locale**; **Data retention** (research documents, AI run logs, tool outputs, publish attempts, raw analytics — duration each); **Export & backup** (JSON + media archive; scheduled backups to local path or S3-compatible storage); **API keys** (name, scopes, last used, revoke; secret shown once); **Danger zone** (transfer ownership; delete workspace — owner, typed confirm, notes that published platform posts remain). **Admin / Debug** (owner/admin): Jobs (Procrastinate queue, Retry), Events (outbox log), Costs, Health (DB, Redis, MinIO, workers, providers, platform APIs).

#### Buttons & actions
Save, Send test, API keys, Export, Backup, Delete workspace, Retry job.

#### Tables / cards / filters
Jobs and Events filterable.

#### Modals & drawers
API key (one-time secret), delete workspace, job detail Sheet.

#### Empty state
No webhooks/keys: one-line explanation + create button.

#### Loading state
Section Skeletons; per-component health spinners.

#### Error state
Transport and health errors shown with time.

#### Mobile behavior
Section list → page; Admin read-only.

#### Data it reads / writes
`GET/PUT /api/v1/settings/workspace`, `PATCH/DELETE /api/v1/workspaces/{ws}`, `GET /api/v1/admin/jobs`, `GET /api/v1/admin/jobs/{id}`, `POST /api/v1/admin/jobs/{id}/retry`, `GET /api/v1/admin/health`, `GET /api/v1/admin/costs`; API keys, backup and event log need new routes (Appendix).

#### Transparency requirements
Retention states what AI data (prompts, tool outputs, sources) is kept and for how long; Admin Costs reconciles with AI usage; all changes are audit-logged.

---

## Appendix — Route gaps

Endpoints these screens need that are missing from vocabulary §14 (proposed for `17-api-architecture.md`): invitations list/revoke `GET`/`DELETE /api/v1/workspaces/{ws}/invitations[/{id}]` (§23); audit-log read `GET /api/v1/settings/audit-logs` (§23); workspace API keys `GET/POST/DELETE /api/v1/settings/api-keys` (§24); export/backup `POST /api/v1/settings/export`, `GET /api/v1/settings/backups` (§24); event log `GET /api/v1/admin/events` (§24); BrandContext preview `GET /api/v1/brands/{brandId}/context` (§21).
