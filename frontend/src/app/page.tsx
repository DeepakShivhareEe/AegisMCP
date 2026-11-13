"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { AlertCircle, RefreshCw, ChevronDown, Boxes } from "lucide-react";
import HeaderBar from "@/components/HeaderBar";
import Aegis3DCore from "@/components/Aegis3DCore";
import TraceExplorer from "@/components/TraceExplorer";
import PolicyFirewall from "@/components/PolicyFirewall";
import HitlQueue from "@/components/HitlQueue";
import FinOpsMetrics from "@/components/FinOpsMetrics";
import ApiKeysTab from "@/components/ApiKeysTab";
import { useAegisStream } from "@/lib/useAegisStream";
import { api, bootstrapSession, API_BASE_URL } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { AgentTrace, MCPServer } from "@/types/aegis";

type TabKey = "explorer" | "firewall" | "hitl" | "finops" | "apikeys";

export default function Page() {
  const [activeTab, setActiveTab] = useState<TabKey>("explorer");
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [spatialHud, setSpatialHud] = useState(true);
  const [heroOpen, setHeroOpen] = useState(true);
  const [shockwaveSignal, setShockwaveSignal] = useState(0);

  const { events, connected, reconnect } = useAegisStream(
    `${API_BASE_URL}/api/v1/stream/events`
  );

  const fetchTraces = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [traceData, serverData] = await Promise.all([
        api.traces(),
        api.mcpServers().catch(() => [] as MCPServer[]),
      ]);
      setTraces(traceData);
      setServers(serverData);
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : (err instanceof Error ? err.message : "Failed to load traces");
      setLoadError(msg);
      console.error("Failed to load traces:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Bootstrap the session/CSRF cookies first, then load data so the first
  // authorized GET cannot race ahead of the session cookie.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await bootstrapSession();
      } catch (err) {
        console.error("Session bootstrap failed:", err);
      }
      if (!cancelled) await fetchTraces();
    })();
    return () => {
      cancelled = true;
    };
  }, [fetchTraces]);

  // Handle SSE events
  useEffect(() => {
    if (events.length === 0) return;
    const latest = events[events.length - 1];
    if (
      latest.type === "span_ingested" ||
      latest.type === "simulator_span" ||
      latest.type === "span_decision" ||
      latest.type === "span_completed"
    ) {
      api.traces().then((data) => setTraces(data)).catch(() => {});
    }
  }, [events]);

  const pendingHitl = useMemo(
    () => traces.filter((trace) => trace.status === "PENDING_HITL").length,
    [traces]
  );

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <HeaderBar
        activeTab={activeTab}
        onTabChange={(tab: string) => setActiveTab(tab as TabKey)}
        traces={traces}
        connected={connected}
        reconnect={reconnect}
        spatialHud={spatialHud}
        onToggleSpatialHud={() => setSpatialHud((value) => !value)}
        onSimulated={() => {
          setSpatialHud(true);
          setHeroOpen(true);
          setShockwaveSignal((value) => value + 1);
        }}
      />
      <main className="mx-auto w-full max-w-[1600px] flex-1 overflow-y-auto px-6 pb-8 pt-5">
        {loadError && (
          <div className="mb-6 flex items-center justify-between rounded-xl border border-red-400/25 bg-red-400/10 p-4 font-mono text-xs text-red-400 backdrop-blur-xl">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{loadError}</span>
            </div>
            <button
              onClick={fetchTraces}
              className="flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1 text-primary transition-colors hover:bg-white/5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Retry</span>
            </button>
          </div>
        )}

        {loading ? (
          <div className="flex h-64 items-center justify-center">
            <div className="mono animate-pulse text-muted">Loading AegisMCP...</div>
          </div>
        ) : (
          <div className="space-y-6">
            {spatialHud && (
              <section aria-label="Spatial topology">
                <div className="flex items-center justify-between px-1 pb-2.5">
                  <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.24em] text-white/30">
                    <Boxes className="h-3.5 w-3.5 text-emerald-400/70" />
                    Spatial topology
                    <span className="text-white/15">
                      / {servers.length || 4} nodes · {traces.length} traces
                    </span>
                  </div>
                  <button
                    onClick={() => setHeroOpen((value) => !value)}
                    aria-expanded={heroOpen}
                    className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 font-mono text-[10px] uppercase tracking-[0.16em] text-white/45 transition-colors hover:text-white/80"
                  >
                    {heroOpen ? "Collapse" : "Expand"}
                    <ChevronDown
                      className={`h-3 w-3 transition-transform ${heroOpen ? "rotate-180" : ""}`}
                    />
                  </button>
                </div>

                {heroOpen ? (
                  <Aegis3DCore
                    traces={traces}
                    servers={servers}
                    pendingHitl={pendingHitl}
                    shockwaveSignal={shockwaveSignal}
                    active={heroOpen}
                  />
                ) : (
                  <button
                    onClick={() => setHeroOpen(true)}
                    className="flex w-full items-center justify-between rounded-xl border border-white/[0.08] bg-zinc-950/70 px-4 py-3 text-left backdrop-blur-xl transition-colors hover:border-emerald-400/25"
                  >
                    <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-white/45">
                      Aegis spatial core collapsed
                    </span>
                    <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-emerald-400/70">
                      {pendingHitl > 0 ? `${pendingHitl} HITL paused` : "Core secure"}
                    </span>
                  </button>
                )}
              </section>
            )}

            {activeTab === "explorer" && <TraceExplorer traces={traces} />}
            {activeTab === "firewall" && <PolicyFirewall />}
            {activeTab === "hitl" && <HitlQueue traces={traces} />}
            {activeTab === "finops" && <FinOpsMetrics />}
            {activeTab === "apikeys" && <ApiKeysTab />}
          </div>
        )}
      </main>
    </div>
  );
}
