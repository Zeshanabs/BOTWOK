# 23 — UI/UX Architecture & Design System

## 23.1 Principles
1. **Information-rich, not cluttered**: dense tables and cards with strong hierarchy; progressive disclosure via drawers/tabs; one primary action per view.
2. **AI-native transparency**: every AI action shows status, sources, tool calls, cost, and what needs approval (doc 05 §6). Nothing happens silently.
3. **Keyboard-first for power users**: command palette (⌘K), shortcuts in Studio and Calendar.
4. **Consistent states**: every list/detail has designed empty, loading (skeleton), error (inline + retry), and offline states.
5. **Local-first feel**: instant optimistic UI for CRUD, streaming for AI, never block on background jobs.

## 23.2 Shell
- Left sidebar (240 px; icon rail 64 px ≤ 1280 px; hidden on mobile), header (56 px: workspace/brand switchers, global search/⌘K, notifications, user menu), content area (max-width 1440 px, 24 px gutters), right **AI drawer** (360–480 px, resizable, contextual to the page: Studio → writer assistant; Competitors → competitor_intel; Analytics → performance_analyst).
- Mobile: bottom tab bar (Home, Studio, Calendar, Approvals, More); sheets replace modals; AI drawer becomes a full-screen sheet.

## 23.3 Tokens
- **Typography**: Inter for UI/body (14/1.5, `tabular-nums`, "cv11"/"ss01" features); Manrope for display headings (`font-display`, 700, tracking -0.02em); JetBrains Mono 12 for code/ids. Scale 12/14/16/20/24/28.
- **Spacing**: 4-px scale; card padding 16–24; section gap 24; page gap 32; content max-width 1440.
- **Radius**: controls 8, cards 14 (`--radius` 10 px), chips 999. **Shadows**: three tokens (`--shadow-card`, `--shadow-raised`, `--shadow-overlay`); light mode uses soft shadows, dark mode uses 1-px light borders instead. No glows.
- **Color** (OKLCH CSS variables in `frontend/src/app/globals.css`, Tailwind v4 `@theme inline`): one anchor hue — **lagoon teal** `--primary` oklch(0.52 0.12 205) — carries every interactive element (buttons, links, focus ring, active nav). Neutrals carry a faint trace of that hue (chroma ≈ 0.005). Colour otherwise only means something: `--success` (green 155), `--warning` (amber 65), `--destructive` (red 25), `--info` (blue 250), and **ember** `--ai` oklch(0.58 0.17 45) reserved for anything AI-produced (provenance chips, agent avatars, the assistant drawer, Command Center). Platform brand colours appear only on platform icons. Status → tone mapping lives in `frontend/src/lib/status.ts`; feature code uses the semantic utilities (`text-success`, `bg-warning/12`, …), never raw palette classes.
- **Dark mode**: first-class via `next-themes` (`class` attribute, system default, header toggle); dark tokens lower lightness and chroma rather than inverting; charts use the same `--chart-1..5` tokens.

## 23.4 Components (shadcn/ui + Botwok extensions)
Cards (metric card with delta + sparkline; content card with platform icon, thumbnail, status badge, time; competitor card; trend card). Tables (TanStack Table: sticky header, column visibility, row selection, bulk actions bar, virtualization > 200 rows, inline status chips). Charts (Recharts: line, bar, stacked bar, heatmap, radar; consistent axis/legend; empty + loading states; "basis/coverage" footnote for normalized metrics). Buttons (primary, secondary, ghost, destructive; loading spinner inside; icon-only with tooltip). Badges (status, platform, availability class, risk, AI-generated). Empty states (icon, one sentence, one primary CTA, optional secondary "learn"). Loading skeletons mirror final layout. Notifications (toasts bottom-right, 5 s; persistent inbox in header). Modals (≤ 2 steps; otherwise a page or drawer). Command palette (⌘K: navigate, create, run AI commands with `/` prefixes: `/research`, `/write`, `/ideas`, `/schedule`). AI chat interface (message list with run cards; run card = checklist of steps + expandable details; sources panel; actions panel; cost footer).

Botwok-specific components: `PlatformPreview` (accurate-enough previews per platform: character truncation, "see more" folds, hashtag rendering, media aspect), `CharacterBudget` (per-platform counters with over-limit state), `RunTimeline`, `SourceList` (credibility/relevance badges, domain favicon, date, cite button), `ClaimVerdicts`, `ApprovalBar`, `AvailabilityBadge`, `CostPill`, `StatusChip`, `CalendarCard`, `WorkflowNode`.

## 23.5 Interaction patterns
- Optimistic updates with rollback toasts for status changes, drag-drop, approvals.
- Streaming: AI responses render progressively; step checklist updates via SSE; cancel always visible.
- Destructive actions: confirm dialog with the exact consequence ("This will delete the post on Instagram; metrics will be lost").
- Forms: inline validation; platform limits shown live; unsaved-changes guard in Studio (autosave every 5 s to a draft version).
- Accessibility: WCAG 2.1 AA; focus rings; ARIA for custom controls; reduced-motion respected; color never the only signal (status chips carry text/icons).

## 23.6 Transparency UI contract (what every AI-touching screen must show)
What the AI is doing (live step), which sources it used (with scores), which tools it called (name, duration, status), what it generated (links to artifacts), what failed (readable reason + retry), what requires approval (action list with Approve/Reject), and what it cost (tokens/$).
