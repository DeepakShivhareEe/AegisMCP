"use client";

import { useState, useEffect, type ReactNode } from "react";
import { Zap, DollarSign, Activity, AlertTriangle, AlertCircle, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import SpatialCard from "@/components/SpatialCard";
import { ApiError } from "@/lib/errors";
import type { AnalyticsSummary } from "@/types/aegis";

export default function FinOpsMetrics() {
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fetchAnalytics = async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const data = await api.analytics();
      setAnalytics(data);
    } catch (err: unknown) {
      let msg = "Failed to load FinOps metrics";
      if (err instanceof ApiError) {
        msg = err.message;
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setErrorMessage(msg);
      console.error("Failed to load analytics:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="mono text-muted animate-pulse">Loading FinOps Metrics...</div>
      </div>
    );
  }

  if (errorMessage || !analytics) {
    return (
      <div className="bg-surface border border-border-subtle rounded-md p-8 text-center space-y-4">
        <AlertCircle className="w-8 h-8 text-red-400 mx-auto" />
        <h3 className="font-mono font-medium text-primary">Unable to load metrics</h3>
        <p className="text-xs text-muted font-mono">{errorMessage || "No analytics data available"}</p>
        <button
          onClick={fetchAnalytics}
          className="inline-flex items-center gap-2 px-3 py-1.5 bg-surface-hover border border-border-subtle text-xs font-mono text-primary rounded hover:border-border-focus transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Retry</span>
        </button>
      </div>
    );
  }

  const totalSpend = analytics.total_spend_24h_usd ?? 0.0;
  const activeSessions = analytics.active_sessions ?? 0;
  const interceptions = analytics.guardrail_interceptions ?? 0;
  const meanTTFT = analytics.mean_ttft_ms ?? 0.0;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-muted" />
          <h2 className="text-lg font-mono font-bold text-primary">FinOps Metrics</h2>
        </div>
        <button
          onClick={fetchAnalytics}
          className="flex items-center gap-1.5 text-xs text-muted hover:text-primary font-mono"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          <span>Refresh</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Total Spend (24h)"
          value={`$${totalSpend.toFixed(4)}`}
          icon={<DollarSign className="text-emerald-400" />}
        />
        <MetricCard
          title="Active Sessions"
          value={activeSessions.toLocaleString()}
          icon={<Activity className="text-secondary" />}
        />
        <MetricCard
          title="Guardrail Interceptions"
          value={interceptions.toLocaleString()}
          icon={<AlertTriangle className="text-amber-400" />}
        />
        <MetricCard
          title="Mean TTFT (ms)"
          value={meanTTFT.toFixed(0)}
          icon={<Zap className="text-muted" />}
        />
      </div>

      <SpatialCard tilt={false} className="p-6">
        <h3 className="mb-4 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-white/45">Model Cost Breakdown</h3>
        <div className="space-y-3">
          {Object.entries(analytics.model_cost_breakdown || {}).map(([model, cost]) => (
            <div key={model} className="flex items-center justify-between border-b border-white/[0.05] py-2 last:border-0">
              <div className="font-mono text-xs text-white/50">{model}</div>
              <div className="font-mono text-xs tabular-nums text-emerald-300">${(cost ?? 0).toFixed(4)}</div>
            </div>
          ))}
          {Object.keys(analytics.model_cost_breakdown || {}).length === 0 && (
            <div className="text-xs text-muted font-mono text-center py-2">No model usage recorded</div>
          )}
        </div>
      </SpatialCard>

      <SpatialCard tilt={false} className="p-6">
        <h3 className="mb-4 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-white/45">Hourly Token Series</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-border-subtle bg-surface/50">
                <th className="px-4 py-3 text-xs font-mono font-bold text-muted">Hour</th>
                <th className="px-4 py-3 text-xs font-mono font-bold text-muted text-right">Tokens</th>
              </tr>
            </thead>
            <tbody>
              {(analytics.hourly_token_series || []).map((entry) => (
                <tr key={entry.hour} className="border-b border-border-subtle/50 last:border-0">
                  <td className="px-4 py-3 mono text-xs text-secondary">{entry.hour}</td>
                  <td className="px-4 py-3 mono text-xs text-primary tabular-nums text-right">{(entry.tokens ?? 0).toLocaleString()}</td>
                </tr>
              ))}
              {(analytics.hourly_token_series || []).length === 0 && (
                <tr>
                  <td colSpan={2} className="px-4 py-4 text-center text-xs text-muted font-mono">
                    No token activity in the last 24 hours
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </SpatialCard>
    </div>
  );
}

function MetricCard({
  title,
  value,
  icon,
}: {
  title: string;
  value: string;
  icon: ReactNode;
}) {
  return (
    <SpatialCard glow="emerald" className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-white/40">{title}</span>
        <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04]">
          {icon}
        </div>
      </div>
      <div className="font-mono text-2xl font-bold tabular-nums text-white">{value}</div>
    </SpatialCard>
  );
}
