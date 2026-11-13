# UI/UX & Visual Design System: Obsidian Monochrome Specification

## 1. Aesthetic Direction
AegisMCP follows an **Ultra-Clean Obsidian Monochrome Engineering Aesthetic** inspired by high-density developer telemetry platforms (Linear, Vercel Observability, Raycast).
- **STRICT PROHIBITION:** Do NOT use bright neon cyan, loud yellow, rainbow gradients, or cartoon illustrations.
- **Surface Hierarchy:** Deep obsidian blacks, crisp 1px zinc borders, subtle glassmorphic overlays, and high-contrast monochrome typography with surgical status indicators.

## 2. Color Palette Tokens (Tailwind / CSS Variables)
- **Canvas Background (`bg-canvas`):** `#09090B` (Zinc 950)
- **Elevated Surface / Card (`bg-surface`):** `#111113`
- **Interactive / Hover Surface (`bg-surface-hover`):** `#18181B` (Zinc 900)
- **Glass Header / Modal (`bg-glass`):** `rgba(17, 17, 19, 0.82)` with `backdrop-filter: blur(12px)`
- **Primary Hairline Border (`border-subtle`):** `#27272A` (Zinc 800)
- **Active / Focus Border (`border-focus`):** `#52525B` (Zinc 600)
- **Primary Text (`text-primary`):** `#FAFAFA` (Zinc 50)
- **Secondary Text (`text-secondary`):** `#A1A1AA` (Zinc 400)
- **Muted / Metadata Text (`text-muted`):** `#71717A` (Zinc 500)

### Semantic Status Accents (Muted, High-Contrast Pill Badges Only)
- **Healthy / Completed:** Text `#34D399` (Emerald 400), Background `rgba(16, 185, 129, 0.1)`, Border `rgba(16, 185, 129, 0.25)`
- **Pending HITL / Warning:** Text `#FBBF24` (Amber 400), Background `rgba(245, 158, 11, 0.1)`, Border `rgba(245, 158, 11, 0.25)`
- **Guardrail Blocked / Error:** Text `#F87171` (Red 400), Background `rgba(239, 68, 68, 0.1)`, Border `rgba(239, 68, 68, 0.25)`

## 3. Typography & Data Density Rules
- **Sans Font:** `Inter` or system geometric sans for UI labels, navigation, and headers.
- **Monospace Font:** `JetBrains Mono` or `Geist Mono` for all Trace IDs, Span IDs, token counts, USD costs (`$0.0042`), latency (`142ms`), and JSON payloads.
- **Tabular Numerals:** All numeric columns MUST apply `font-variant-numeric: tabular-nums` (`tabular-nums` in Tailwind) so live-streaming numbers never jitter horizontally.
- **Border Radius:** Crisp `rounded-md` (`6px`) for cards and buttons, `rounded-sm` (`4px`) for status badges.

## 4. Layout Structure
- **Top Command Header (`h-14`):** Brand mark (`AEGIS // MCP`), Environment selector (`prod-us-east`), Live SSE Connection Indicator (pulsing emerald dot), **"Simulate Agent Traffic"** trigger button, and Pending HITL badge counter.
- **Navigation Tabs:**
  1. `Live Trace Explorer` (Split-view trace table + span waterfall + JSON payload drawer)
  2. `MCP Policy Firewall` (Server cards + live editable guardrail rules + regex pattern chips)
  3. `HITL Approval Queue` (Interactive diff/payload review + Approve/Reject action bar)
  4. `FinOps & Token Telemetry` (Model cost breakdown bars + loop circuit-breaker logs)