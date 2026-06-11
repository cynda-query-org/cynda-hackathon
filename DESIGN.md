# DESIGN.md — Cynda Landing Page (Beta Waitlist)

## Overview

A **single-page landing page** for **Cynda** — a self-service analytics Slack bot that connects companies to BigQuery. Goal: capture beta-tester emails. The aesthetic is a modern, bold startup — somewhere between *Vercel* and *Linear*, with an ember warmth drawn from Cyndaquil's color palette.

Built as a single `index.html` with embedded `<style>` and `<script>`. No external JS libraries or frameworks.

---

## Brand & Concept

**Product name:** Cynda
**Tagline:** _"Your analytics team, already in Slack."_
**Sub-copy:** _"Cynda connects to your database and answers your team's questions on Slack. No JIRA tickets. Unlock the insights faster than your next planning session."_

The palette draws color inspiration from **Cyndaquil** — warmth, quick ignition, energy — translated into a modern startup aesthetic.

---

## Color Palette

| Role | Name | Hex | CSS Variable |
|---|---|---|---|
| Background | Deep Slate | `#0F1117` | `--bg` |
| Surface / Cards | Dark Blue-Grey | `#181C27` | `--surface` |
| Primary Accent | Ember Orange | `#F25C1E` | `--ember` |
| Secondary Accent | Flame Yellow | `#F5A623` | `--flame` |
| Highlight Glow | Soft Ember | `#FF7A3C` | `--glow` |
| Body Text | Off-White | `#E8E8E4` | `--text` |
| Muted Text | Cool Grey | `#6E7484` | `--muted` |
| Border / Divider | Subtle Slate | `#252A38` | `--border` |

---

## Typography

- **Display / Headline:** `Space Grotesk` (Google Fonts) — bold, geometric. Weight 700.
- **Body / UI:** `DM Sans` (Google Fonts) — clean, modern. Weights 400 and 500.

Both loaded from Google Fonts CDN.

---

## Layout — Single Page, Sections Top to Bottom

### 1. Nav Bar (sticky)

- Fixed, `height: 64px`, transparent. On scroll past 60px: `rgba(15,17,23,0.85)` background + `backdrop-filter: blur(12px)` + bottom border in `--border`.
- Left: Logo wordmark `"Cynda"` in `Space Grotesk` 700, ember orange, `24px`.
- Right: `"Join Beta"` button — outlined style (`border: 1.5px solid --ember`, transparent bg, ember text), `font-size: 16px`, padding `8px 20px`. Hover: fills ember, text goes dark, `scale(1.02)`.
- Nav CTA clicks scroll to `#hero-form` (smooth).

### 2. Hero Section (full viewport height)

- Full-height section with centered content (`align-items: center`, `text-align: center`). Padding: `100px 24px 80px`.
- Two CSS pseudo-elements for ambient texture:
  - `::before` — radial gradient glow (ember orange, 13% opacity) behind the headline.
  - `::after` — dot-matrix pattern (18% opacity dots at 28px intervals), masked to an ellipse.
- Headline (`h1`, `Space Grotesk` 700, `clamp(52px, 8vw, 88px)`, `letter-spacing: -2px`):
  > "Your analytics team,
  > **already in Slack.**" (second line in ember orange via `.accent`)
- Sub-copy: `20px`, muted grey, `max-width: 520px`, centered, `line-height: 1.7`.
- Email capture form directly below, `max-width: 460px`, centered:
  - Input: `"Your work email"` — dark surface bg, subtle border, ember focus border. Font size `17px`.
  - Button: `"Get Early Access"` — filled ember, dark text, `border-radius: 8px`, font size `17px`. Hover: `--glow` bg + glow box-shadow + `scale(1.02)`.
  - Note below form: `"🔒 No spam. Just early access."` in muted grey `15px`.
  - On valid submit: async POST to backend (see **Backend** section). Form + note hide, inline success message appears (`"You're on the list! We'll be in touch. 🎉"`) in flame yellow on a translucent yellow background.
  - On backend error: button re-enables, error message shows the server-returned error text.
  - Client-side email validation; error message shown below form on invalid submit.
- Page load: headline, sub-copy, and form wrap each fade up with a staggered animation (`0.1s`, `0.28s`, `0.42s` delays, `0.5s` duration).

### 3. How It Works (3 steps)

- Top border in `--border`.
- Section label: `"HOW IT WORKS"` — `14px`, `letter-spacing: 2px`, uppercase (via CSS), ember orange.
- Section title: `"How Cynda works"` — `Space Grotesk` 700, `clamp(36px, 5vw, 56px)`, centered.
- Three-column grid (`repeat(3, 1fr)`, `gap: 24px`). Stacks to single column on mobile (max-width 860px), max-width 480px.
- Each step card (`background: --surface`, `border: 1.5px solid --border`, `border-radius: 12px`, padding `36px 28px`):
  - Title: `Space Grotesk` 700, `22px`, off-white.
  - Description: `17px`, muted grey, `line-height: 1.65`.
  - Hover: border transitions to `rgba(242,92,30,0.4)` with matching box-shadow outline.
- Steps:
  1. **Connect** — "Provide access to the data. No complex setup, no infrastructure changes."
  2. **Ask** — "Type your question in any Slack channel. Plain English — no SQL knowledge required."
  3. **Get answers** — "Cynda replies on Slack, using your language and optionally provides the SQL code for analysts."

### 4. Logos / Social Proof Strip

- `padding: 60px 24px`, top border in `--border`.
- Centered label: `"Works with tools your team already uses"` — `15px`, muted grey.
- **Two rows** of logos, flex, centered, `gap: 56px`, wraps on small screens. Second row has `margin-top: 36px`.
- **Row 1 — colored, full opacity** (`opacity: 0.72`, no filter):
  - **Slack** — 4-color Slack SVG (`28×28`) + wordmark.
  - **BigQuery** — blue hexagon SVG with magnifying glass (`28×28`) + wordmark.
- **Row 2 — grayscale, dimmed** (`opacity: 0.38`, `filter: grayscale(1)`). Hover: `opacity: 0.55`.
  - **Teams** — Microsoft Teams SVG (`28×28`) + wordmark.
  - **Snowflake** — Snowflake SVG (`28×28`) + wordmark.
  - **Redshift** — Amazon Redshift cylinder stack SVG (`28×28`) + wordmark.
- Logo wordmarks: `DM Sans` 500, `20px`, `--text`, `letter-spacing: -0.3px`.

### 5. Second CTA / Closing

- Top border in `--border`. Content centered (`align-items: center`, `text-align: center`).
- Section title: `"Join the waitlist"` — `Space Grotesk` 700, `clamp(36px, 5vw, 56px)`.
- Repeat email capture form (same structure and behavior as hero form, without the form note).
- Muted note below: `"Limited spots available."` — `15px`.

### 6. Footer

- `padding: 28px 48px`. Top border in `--border`. Flex row, space-between, wraps on mobile.
- Left: `Cynda © 2026` — `16px` muted grey. "Cynda" in `Space Grotesk` 700 ember orange.
- Right: flex row with `gap: 24px`, wraps on small screens:
  - `"Privacy Policy"` link → `/privacy-policy.html`
  - `"Terms of Service"` link → `/terms-of-service.html`
  - `"support@cynda.tech"` mailto link
  - All links `16px` muted grey, transition to off-white on hover.

---

## Backend

- Form submissions POST to `https://cynda-landing-page-staging.up.railway.app/subscribe`.
- Request body: `{ "email": "<value>" }` (JSON).
- On `!res.ok`: throws with error detail from JSON response body.
- Success: hides form (and note if present), shows `.form-success` element.
- Failure: re-enables submit button, shows error text in `.form-error`.

---

## Interactions & Motion

- **Page load:** Headline, sub-copy, and form wrap each fade up with staggered `fadeUp` animation.
- **Sticky nav:** On scroll past 60px, background frosted-glass effect activates.
- **Email input focus:** Border transitions from `--border` to ember orange.
- **CTA button hover:** Background fills to `--glow`, glow box-shadow, `scale(1.02)`.
- **Step card hover:** Border and box-shadow transition to ember orange outline.
- **Nav CTA click:** Smooth-scrolls to hero form.
- **Form submit:** Validates email client-side, then async POST to backend. On success, replaces form with inline success message. On failure, shows server error.

No heavy scroll animations. Fast-feeling — productivity tool, not a portfolio site.

---

## Responsive Breakpoints

- **≤ 860px:** Nav padding reduced to `0 24px`. Step cards stack to single column (max-width 480px). Section padding shrinks to `72px 24px`.
- **≤ 540px:** Hero headline drops to `clamp(44px, 12vw, 56px)` / `-1.5px` tracking. Sub-copy drops to `18px`. Email form becomes full-width column (input and button each `width: 100%`, `font-size: 17px`, `padding: 16px 20px`). Footer stacks vertically, centered, padding `24px`. Nav CTA shrinks to `font-size: 15px`, padding `8px 16px`.
