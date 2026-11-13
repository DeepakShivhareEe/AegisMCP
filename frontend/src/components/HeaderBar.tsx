"use client";

import { useEffect, useState } from "react";
import {
  ShieldCheck,
  AlertCircle,
  CheckCircle,
  Database,
  Wifi,
  WifiOff,
  Zap,
  Layout,
  Loader2,
  Key,
  Box,
  Activity,
} from "lucide-react";
import { api, MeResponse } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { AgentTrace } from "@/types/aegis";

const TABS = [
  { key: "explorer", label: "Live Trace Explorer", Icon: Layout },
  { key: "firewall", label: "MCP Policy Firewall", Icon: Database },
  { key: "hitl", label: "HITL Approval Queue", Icon: CheckCircle },
  { key: "finops", label: "FinOps Metrics", Icon: Zap },
  { key: "apikeys", label: "API Keys & SDK", Icon: Key },
];

export default function HeaderBar({
  activeTab,
  onTabChange,
  traces,
  connected,
  reconnect,
  spatialHud = true,
  onToggleSpatialHud,
  onSimulated,
}: {
  activeTab: string;
  onTabChange: (tab: string) => void;
  traces: AgentTrace[];
  connected: boolean;
  reconnect: () => void;
  spatialHud?: boolean;
  onToggleSpatialHud?: () => void;
  onSimulated?: () => void;
}) {
  const [me, setMe] = useState<MeResponse | null>(null);
  const [pendingHitlCount, setPendingHitlCount] = useState(0);
  const [simulating, setSimulating] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);

  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
    setPendingHitlCount(traces.filter((t) => t.status === "PENDING_HITL").length);
  }, [traces]);

  const handleSimulate = async () => {
    setSimulating(true);
    setSimError(null);
    try {
      await api.simulatorTrigger();
      onSimulated?.();
    } catch (err: unknown) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Simulator failed";
      setSimError(msg);
      console.error("Simulator trigger error:", err);
    } finally {
      setSimulating(false);
    }
  };

  const statusColor = connected ? "text-emerald-400" : "text-red-400";
  const statusBg = connected
    ? "bg-emerald-400/10 border-emerald-400/25"
    : "bg-red-400/10 border-red-400/25";

  return (
    <header className="sticky top-0 z-30 px-3 pt-3">
      <div className="relative mx-auto max-w-[1600px] overflow-hidden rounded-2xl border border-white/[0.08] bg-zinc-950/75 shadow-[0_24px_70px_-40px_rgba(0,0,0,1)] backdrop-blur-2xl">
        <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/25 to-transparent" />

        <div className="flex h-16 w-full items-center justify-between gap-3 px-4">
          <div className="flex items-center gap-3">
            <div className="relative h-9 w-9" aria-hidden>
              <div className="absolute inset-0 rotate-45 rounded-[7px] border border-white/25 bg-gradient-to-br from-white/25 via-white/5 to-transparent shadow-[inset_0_1px_0_rgba(255,255,255,0.45)]" />
              <div className="absolute inset-[6px] rotate-[20deg] rounded-[4px] border border-emerald-300/40 bg-emerald-400/10" />
              <div className="absolute inset-[13px] rotate-[20deg] rounded-[2px] bg-emerald-300/80 blur-[0.5px]" />
            </div>
            <div className="leading-none">
              <span className="chrome-text font-mono text-lg font-bold tracking-tighter">
                AEGIS MCP
              </span>
              <span className="mt-1 block text-[9px] uppercase tracking-[0.28em] text-white/35">
                Spatial Command Center
              </span>
            </div>
            <span className="hidden rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-0.5 text-[10px] font-mono text-white/45 sm:inline">
              prod-us-east
            </span>
          </div>

          <div className="flex items-center gap-2">
            <div className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 lg:flex">
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
              <span className="text-[10px] font-mono uppercase tracking-[0.12em] text-white/55">
                JWT HttpOnly + CSRF + SHA-256
              </span>
              {typeof me?.rate_limit_remaining === "number" && (
                <span className="text-[10px] font-mono text-white/30">
                  · {me.rate_limit_remaining} req
                </span>
              )}
            </div>

            <div className={`flex items-center gap-2 rounded-full border px-3 py-1.5 ${statusBg}`}>
              {connected ? (
                <>
                  <Wifi className="h-3.5 w-3.5 text-emerald-400" />
                  <span className="flex h-3 items-end gap-[2px]" aria-hidden>
                    {[0, 1, 2, 3, 4].map((index) => (
                      <span
                        key={index}
                        className="wave-bar w-[2px] rounded-full bg-emerald-400"
                        style={{
                          height: `${7 + (index % 3) * 4}px`,
                          animationDelay: `${index * 0.12}s`,
                        }}
                      />
                    ))}
                  </span>
                  <span className={`text-[10px] font-mono uppercase tracking-[0.14em] ${statusColor}`}>
                    Live
                  </span>
                </>
              ) : (
                <>
                  <WifiOff className="h-3.5 w-3.5 text-red-400" />
                  <button
                    onClick={reconnect}
                    className="text-[10px] font-mono uppercase tracking-[0.14em] text-red-400 underline hover:text-red-300"
                  >
                    Reconnect
                  </button>
                </>
              )}
            </div>

            <button
              onClick={onToggleSpatialHud}
              aria-pressed={spatialHud}
              className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-[10px] font-mono uppercase tracking-[0.14em] transition-all ${
                spatialHud
                  ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300"
                  : "border-white/10 bg-white/[0.03] text-white/45 hover:text-white/70"
              }`}
            >
              <Box className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">HUD</span>
            </button>

            <button
              disabled={simulating}
              onClick={handleSimulate}
              className="group relative flex items-center gap-2 overflow-hidden rounded-full border border-white/15 px-4 py-2 text-xs font-medium text-white transition-all hover:border-white/30 disabled:opacity-60"
            >
              <span className="absolute inset-0 animate-shimmer opacity-60" aria-hidden />
              <span className="relative flex items-center gap-2">
                {simulating ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Zap className="h-3.5 w-3.5 text-emerald-300" />
                )}
                <span className="font-mono uppercase tracking-[0.12em]">
                  {simulating ? "Generating" : "Simulate Traffic"}
                </span>
              </span>
            </button>

            {pendingHitlCount > 0 && (
              <div className="flex items-center gap-1.5 rounded-full border border-amber-400/30 bg-amber-400/10 px-3 py-1.5">
                <AlertCircle className="h-3.5 w-3.5 text-amber-400" />
                <span className="text-[10px] font-mono font-medium uppercase tracking-[0.12em] text-amber-300">
                  {pendingHitlCount} HITL
                </span>
              </div>
            )}
          </div>
        </div>

        {simError && (
          <div className="flex items-center justify-between border-t border-red-400/25 bg-red-400/10 px-4 py-2 text-[11px] font-mono text-red-400">
            <span>Simulation error: {simError}</span>
            <button onClick={() => setSimError(null)} className="text-white/40 hover:text-white">
              ×
            </button>
          </div>
        )}

        <nav className="border-t border-white/[0.06] bg-black/20">
          <div className="flex h-11 items-center gap-2 overflow-x-auto px-3 scrollbar-hide">
            {TABS.map(({ key, label, Icon }) => {
              const isActive = activeTab === key;
              return (
                <button
                  key={key}
                  onClick={() => onTabChange(key)}
                  className={`relative flex items-center gap-2 whitespace-nowrap rounded-full px-3.5 py-1.5 text-[11px] font-medium transition-all ${
                    isActive
                      ? "border border-white/15 bg-white/[0.07] text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]"
                      : "border border-transparent text-white/40 hover:text-white/75"
                  }`}
                >
                  <Icon className={`h-3 w-3 ${isActive ? "text-emerald-300" : ""}`} />
                  {label}
                  {isActive && (
                    <span className="absolute inset-x-3 -bottom-px h-px bg-gradient-to-r from-transparent via-emerald-300/70 to-transparent" />
                  )}
                </button>
              );
            })}
            <div className="ml-auto hidden items-center gap-2 pr-1 text-[10px] font-mono uppercase tracking-[0.16em] text-white/25 md:flex">
              <Activity className="h-3 w-3" />
              {traces.length} traces
            </div>
          </div>
        </nav>
      </div>
    </header>
  );
}
