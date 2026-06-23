# Frontend Layout Restructure: Collapsible Agent Workflow

**Date:** 2026-06-23
**Scope:** `frontend/` only — HTML, CSS, JS. No backend, no API, no agent logic changes.
**Goal:** Free up screen real estate for the Order Draft form by moving the Agent Workflow step list out of the main layout and into a right-side drawer that the user opens on demand.

## Motivation

The current three-column layout (PDF | Agent Workflow | Order Draft) gives equal visual weight to a column whose value is **status display only** — the user reads the five checkmarks at most once per PDF. The Order Draft, by contrast, is the column the user actually edits. Reallocating that middle column to the Order Draft form gives the editable content more room without losing access to the workflow status.

## Current State (Baseline)

`frontend/index.html`, `frontend/styles.css`, `frontend/app.js` together produce:

```
┌────────────────┬────────────────┬────────────────────┐
│  Original PO   │ Agent Workflow │   Order Draft      │
│  (PDF upload + │ (5-step ✓ list)│   (header form +   │
│   iframe)      │                │    items + buttons)│
└────────────────┴────────────────┴────────────────────┘
```

CSS grid: `grid-template-columns: 1fr 1fr 1.2fr`

JS data flow (unchanged by this work):
- `renderSteps(steps)` populates `#steps` `<ol>` with `<li class="done">…</li>` per agent
- `renderDraft(order)` populates the header inputs, items list, total, status
- Submit/release buttons call `/api/submit`

## Target State

### Layout

```
┌──────────────────────────────────────────────────────┐
│ PO Intake Agent                 [Agent Workflow ▸]   │  ← header
├──────────────────┬───────────────────────────────────┤
│  Original PO     │  Order Draft                      │
│  (PDF upload +   │  (header form + items + buttons)  │
│   iframe)        │                                   │
└──────────────────┴───────────────────────────────────┘
```

CSS grid: `grid-template-columns: 1fr 1.5fr` (PDF gets less space; the form has many fields and benefits from the wider column).

### Drawer

```
                       click [Agent Workflow ▸]
                                  ↓
┌──────────────────────────────────────┐ ┌─────────────────┐
│ ▒▒▒▒ overlay (rgba(0,0,0,0.3)) ▒▒▒▒ │ │ Agent Workflow  │
│ ▒                                  ▒ │ │ ─────────────── │
│ ▒  (page content dimmed)           ▒ │ │ ✓ intake        │
│ ▒                                  ▒ │ │ ✓ extraction    │
│ ▒                                  ▒ │ │ ✓ validation    │
│ ▒                                  ▒ │ │ ✓ exception     │
│ ▒                                  ▒ │ │ ✓ draft         │
└──────────────────────────────────────┘ └─────────────────┘
                                            slides in from right, 320px wide
```

### Header Toggle Button

- Placement: top-right of the existing `<header>`.
- Idle label: `Agent Workflow ▸`
- Open label: `Agent Workflow ◂`
- Post-process badge: when `/api/process` returns with all steps `ok: true`, append `5/5 ✓` to the label so the user has a passive completion signal without opening the drawer.
- Reset to `Agent Workflow ▸` (no badge) on each new file upload.

### Drawer Behavior

| Trigger | Action |
|---|---|
| Click header button | Toggle drawer open/closed |
| Click overlay | Close |
| Press `Esc` | Close |
| `/api/process` completes | Do **not** auto-open; update badge only |
| New file selected | Reset badge, do not auto-open |

- Animation: CSS `transform: translateX(100%)` ↔ `translateX(0)`, ~200ms transition.
- Overlay fades in/out via opacity transition, sits between main content and drawer (`z-index` ordering: main < overlay < drawer).
- When closed, drawer has `aria-hidden="true"`; when open, `aria-hidden="false"`.

## Components Changed

### `frontend/index.html`

- **Header**: add `<button id="workflow-toggle" class="drawer-toggle">Agent Workflow ▸</button>` inside the existing `<header>`, right-aligned.
- **Main grid**: remove the entire `<section class="col" id="col-steps">…</section>`. Keep `#col-pdf` and `#col-draft` only.
- **Drawer + overlay**: append two siblings to `<body>` after `<main>`:
  ```html
  <div id="drawer-overlay" hidden></div>
  <aside id="workflow-drawer" aria-hidden="true">
    <h2>Agent Workflow</h2>
    <ol id="steps"></ol>
  </aside>
  ```
  The `<ol id="steps">` ID is preserved so `renderSteps()` in `app.js` does not need to change its DOM target.

### `frontend/styles.css`

- Change `.cols` grid columns from `1fr 1fr 1.2fr` to `1fr 1.5fr`.
- Add `header` flex layout so title and toggle button sit on the same row, button right-aligned.
- Add styles:
  - `.drawer-toggle` — outline button matching header style; badge span inside.
  - `#workflow-drawer` — fixed positioned right edge, width 320px, full viewport height, `transform: translateX(100%)`, white background, left border + light shadow.
  - `#workflow-drawer.open` — `transform: translateX(0)`.
  - `#drawer-overlay` — fixed full-viewport, `background: rgba(0,0,0,0.3)`, opacity 0 hidden, opacity 1 visible; `pointer-events: none` when hidden so clicks pass through.
  - Transitions: `transform 200ms ease`, `opacity 200ms ease`.
- Preserve existing `#steps li`, `#steps li.done` styles (they still apply inside the drawer).

### `frontend/app.js`

New responsibilities:
- Cache references to `#workflow-toggle`, `#workflow-drawer`, `#drawer-overlay`.
- `openDrawer()` / `closeDrawer()` / `toggleDrawer()` — add/remove `.open` on drawer, toggle `hidden` on overlay, update `aria-hidden`, update button label arrow.
- Wire up listeners: button click → toggle; overlay click → close; `document` `keydown` Esc → close.
- `updateWorkflowBadge(steps)` — after `/api/process`, if all `steps[i].ok === true`, set button text to `Agent Workflow ▸ 5/5 ✓`; otherwise show `Agent Workflow ▸ X/5` where X is the count of `ok`.
- Reset badge to `Agent Workflow ▸` when the file input changes (new upload starts).

Unchanged:
- `renderSteps(steps)` — same function, same target (`#steps`), now located inside the drawer.
- `renderDraft(order)`, `collectDraft()`, all `/api/process` and `/api/submit` logic.

## Behavior on `/api/process`

1. User selects PDF → file input `change` event → badge reset to `Agent Workflow ▸`, drawer stays in whatever state it was in (closed by default on page load).
2. `fetch("/api/process")` resolves.
3. `renderSteps(steps)` populates the drawer's `<ol>` (invisible if drawer is closed — fine).
4. `renderDraft(order)` populates the form.
5. `updateWorkflowBadge(steps)` updates the header button label.
6. User may click the button at any time to see the breakdown.

## Out of Scope

- Real-time step progress streaming (current API is one-shot; not changing).
- Storing drawer open/closed preference across sessions.
- Mobile-specific responsive layout (current app is desktop-first; existing media behavior is preserved as-is).
- Any backend, pipeline, or agent change.
- Test changes — there are no frontend automated tests; backend tests are unaffected.

## Manual Verification

After implementation, the developer should manually verify in a browser:

1. Page loads with two columns visible, drawer closed, button labeled `Agent Workflow ▸`.
2. Upload `samples/valid.pdf`:
   - Form populates in the middle column.
   - Header button updates to `Agent Workflow ▸ 5/5 ✓`.
   - Drawer remains closed.
3. Click `Agent Workflow ▸` → drawer slides in from right, overlay dims main content, five green checkmarks visible.
4. Click overlay → drawer slides out, overlay fades.
5. Open drawer, press `Esc` → drawer closes.
6. Upload `samples/missing_customer.pdf`:
   - Badge shows accurate ok count (e.g. `4/5` if a step failed; but in current pipeline all five steps return `ok:true` regardless of issues, so badge will read `5/5 ✓` — issue surfacing remains via the form's `status` field and the items list). The badge is a workflow-completion signal, not a validation signal.

## Risk and Mitigation

| Risk | Mitigation |
|---|---|
| `#steps` referenced from `app.js` elsewhere besides `renderSteps` | Code search before editing confirms no other reference exists |
| Overlay blocks clicks on PDF iframe even when hidden | Use `hidden` attribute + `pointer-events: none` when closed, removed when open |
| Esc handler fires when user is typing in a form field | Acceptable — Esc on form fields doesn't have an existing competing behavior in this app; closing the drawer on Esc-anywhere is the expected UX |
| Badge wording ambiguity (steps ok ≠ validation ok) | Documented above; badge is explicitly a workflow-completion signal, not a "ready to submit" signal — the form's status field remains the source of truth for submission readiness |

## File Inventory

Files to modify:
- `frontend/index.html`
- `frontend/styles.css`
- `frontend/app.js`

Files NOT to modify:
- Anything under `backend/`
- Anything under `tests/`
- `requirements.txt`, `.env`, `.env.example`
