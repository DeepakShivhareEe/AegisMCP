# AegisMCP — Awwwards 3D Spatial WebGL & Glassmorphic HUD Specification

## 1. Visual Identity: "Obsidian Spatial Telemetry"
- **Base Void Canvas:** `#050507` with a subtle 3D perspective grid floor and ambient volumetric fog.
- **Floating Glass HUD Surfaces:** `bg-zinc-950/65 backdrop-blur-2xl border border-white/[0.08] shadow-[0_20px_70px_-15px_rgba(0,0,0,0.85)]` with a top 1px specular highlight (`before:bg-gradient-to-r before:from-transparent before:via-white/20 before:to-transparent`).
- **3D Interactive Elements:**
  1. **Ambient WebGL Background Canvas (`Fixed z-0`):** Subtle floating particle field + deep obsidian grid that reacts to cursor parallax.
  2. **Interactive 3D MCP Gateway Core (`Hero HUD Module`):** An interactive Three.js / React Three Fiber 3D scene displaying:
     - Central **Aegis Security Core** (dual counter-rotating wireframe icosahedron + inner glowing energy sphere).
     - 4 Orbiting **MCP Server Nodes** (`postgres-prod-mcp`, `github-repo-mcp`, `filesystem-sandbox-mcp`, `stripe-billing-mcp`) connected to the core via glowing 3D curves.
     - **Real-Time Telemetry Pulse:** Whenever a trace is simulated, blocked, or paused in HITL, the 3D core pulses with the corresponding semantic color (`#10B981` Emerald, `#EF4444` Crimson, `#F59E0B` Amber).
  3. **3D Mouse-Tracking Specular Tilt Cards (`TiltCard.tsx`):** Spring-physics 3D tilt (`perspective: 1000px`) + dynamic cursor-following border glow on all FinOps KPI cards and MCP Firewall server cards.