"use client";

import { useState, useMemo, useCallback, type ReactNode } from "react";
import { Activity, AlertCircle, CheckCircle, Zap, ChevronRight, X, FileText, Code2, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";
import SpatialCard from "@/components/SpatialCard";
import type { AgentTrace, TraceSpan } from "@/types/aegis";

const STATUS_CONFIG: Record<string, { color: string; bg: string; border: string; label: string }> = {
  COMPLETED: { color: "text-emerald-400", bg: "bg-emerald-400/10", border: "border-emerald-400/25", label: "Completed" },
  BLOCKED: { color: "text-red-400", bg: "bg-red-400/10", border: "border-red-400/25", label: "Blocked" },
  PENDING_HITL: { color: "text-amber-400", bg: "bg-amber-400/10", border: "border-amber-400/25", label: "Pending HITL" },
  LOOP_KILLED: { color: "text-red-400", bg: "bg-red-400/10", border: "border-red-400/25", label: "Loop Killed" },
  RUNNING: { color: "text-secondary", bg: "bg-surface-hover", border: "border-border-subtle", label: "Running" },
};

const SPAN_TYPE_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  LLM_INFERENCE: { label: "LLM", color: "text-blue-400", bg: "bg-blue-400/10" },
  MCP_TOOL_CALL: { label: "TOOL", color: "text-purple-400", bg: "bg-purple-400/10" },
  RAG_RETRIEVAL: { label: "RAG", color: "text-emerald-400", bg: "bg-emerald-400/10" },
  GUARDRAIL_INTERCEPT: { label: "GUARD", color: "text-red-400", bg: "bg-red-400/10" },
};

const SPAN_STATUS_CONFIG: Record<string, { color: string; bg: string; label: string }> = {
  OK: { color: "text-emerald-400", bg: "bg-emerald-400/10", label: "OK" },
  BLOCKED: { color: "text-red-400", bg: "bg-red-400/10", label: "BLOCKED" },
  PENDING_APPROVAL: { color: "text-amber-400", bg: "bg-amber-400/10", label: "PENDING" },
  ERROR: { color: "text-red-400", bg: "bg-red-400/10", label: "ERROR" },
};

interface TraceDetailData {
  trace: AgentTrace;
  spans: TraceSpan[];
}

export default function TraceExplorer({ traces }: { traces: AgentTrace[] }) {
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [selectedTrace, setSelectedTrace] = useState<TraceDetailData | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [selectedSpan, setSelectedSpan] = useState<TraceSpan | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const filtered = useMemo(() => {
    return traces.filter((t) => {
      const matchStatus = filterStatus === "all" || t.status === filterStatus;
      const agentName = t.agent_name || "";
      const traceId = t.id || "";
      const searchLower = search.toLowerCase();
      const matchSearch =
        agentName.toLowerCase().includes(searchLower) ||
        traceId.toLowerCase().includes(searchLower);
      return matchStatus && matchSearch;
    });
  }, [traces, filterStatus, search]);

  const handleTraceClick = useCallback(async (traceId: string) => {
    setLoadingDetail(true);
    setErrorMessage(null);
    try {
      const detail = await api.traceDetail(traceId);
      setSelectedTrace(detail);
      setSelectedSpan(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load trace detail";
      setErrorMessage(msg);
      setSelectedTrace(null);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  const closeInspector = useCallback(() => {
    setSelectedTrace(null);
    setSelectedSpan(null);
  }, []);

  const formatJson = (obj: Record<string, any> | null) => {
    if (!obj) return "{}";
    return JSON.stringify(obj, null, 2);
  };

  const getMaxLatency = (spans: TraceSpan[]) => {
    return Math.max(...spans.map((s) => s.latency_ms), 1);
  };

  const renderLatencyBar = (latency: number, maxLatency: number) => {
    const width = maxLatency > 0 ? Math.max(2, (latency / maxLatency) * 100) : 0;
    return (
      <div className="h-3 bg-border-subtle rounded-full overflow-hidden" style={{ width: "100px" }}>
        <div
          className="h-full bg-primary transition-all duration-300"
          style={{ width: `${width}%` }}
        />
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <SpatialCard
        tilt={false}
        className="p-5"
        contentClassName="flex flex-col gap-5 md:flex-row md:items-end"
      >
        <div className="flex-1 min-w-[200px]">
          <label className="block text-xs text-muted mb-1 mono">Search traces</label>
          <input
            type="text"
            className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-white placeholder:text-white/25 outline-none transition-colors focus:border-emerald-400/40"
            placeholder="Agent name or trace ID"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap items-center gap-2 md:pb-1">
          {[
            "all",
            "COMPLETED",
            "BLOCKED",
            "PENDING_HITL",
            "LOOP_KILLED",
            "RUNNING",
          ].map((status) => (
            <button
              key={status}
              onClick={() => setFilterStatus(status)}
              className={`rounded-full border px-3 py-1.5 font-mono text-[11px] uppercase tracking-[0.08em] transition-all ${
                filterStatus === status
                  ? "border-emerald-400/35 bg-emerald-400/10 text-emerald-300"
                  : "border-white/10 bg-white/[0.02] text-white/40 hover:border-white/20 hover:text-white/75"
              }`}
            >
              {status === "all" ? "All" : status}
            </button>
          ))}
        </div>
      </SpatialCard>

      {loadingDetail && (
        <div className="flex items-center gap-2 text-xs font-mono text-muted">
          <div className="animate-spin rounded-full border-2 border-border-subtle border-t-primary h-3.5 w-3.5" />
          <span>Loading trace detail...</span>
        </div>
      )}

      {errorMessage && (
        <div className="flex items-center gap-2 rounded-lg border border-red-400/25 bg-red-400/10 p-3 font-mono text-xs text-red-400 backdrop-blur-xl">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{errorMessage}</span>
          <button
            onClick={() => setErrorMessage(null)}
            className="ml-auto text-muted hover:text-primary"
          >
            ×
          </button>
        </div>
      )}

      <SpatialCard tilt={false} className="overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="border-b border-white/[0.08] bg-white/[0.02]">
              <th className="px-4 py-3 text-xs font-mono font-bold text-muted">Trace ID</th>
              <th className="px-4 py-3 text-xs font-mono font-bold text-muted">Agent</th>
              <th className="px-4 py-3 text-xs font-mono font-bold text-muted text-center">Environment</th>
              <th className="px-4 py-3 text-xs font-mono font-bold text-muted text-center">Status</th>
              <th className="px-4 py-3 text-xs font-mono font-bold text-muted text-right">Tokens</th>
              <th className="px-4 py-3 text-xs font-mono font-bold text-muted text-right">Cost (USD)</th>
              <th className="px-4 py-3 text-xs font-mono font-bold text-muted text-right">Latency (ms)</th>
              <th className="px-4 py-3 text-xs font-mono font-bold text-muted text-center">Steps</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((trace) => {
              const config = STATUS_CONFIG[trace.status] || STATUS_CONFIG.RUNNING;
              const tokens = trace.total_tokens ?? 0;
              const cost = trace.total_cost_usd ?? 0.0;
              const latency = trace.total_latency_ms ?? 0;
              const steps = trace.step_count ?? 0;

              return (
                <tr
                  key={trace.id}
                  className="cursor-pointer border-b border-white/[0.05] transition-colors last:border-0 hover:bg-white/[0.04]"
                  onClick={() => handleTraceClick(trace.id)}
                >
                  <td className="px-4 py-3 mono text-sm text-secondary">{trace.id}</td>
                  <td className="px-4 py-3 text-sm text-primary">{trace.agent_name}</td>
                  <td className="px-4 py-3 text-xs text-muted mono text-center">{trace.environment}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`status-badge ${config.bg} ${config.border} ${config.color}`}>
                      {config.label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right mono text-sm text-primary tabular-nums">{tokens.toLocaleString()}</td>
                  <td className="px-4 py-3 text-right mono text-sm text-secondary tabular-nums">${cost.toFixed(4)}</td>
                  <td className="px-4 py-3 text-right mono text-sm text-muted tabular-nums">{latency}</td>
                  <td className="px-4 py-3 text-center mono text-sm text-muted">{steps}</td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-muted font-mono text-xs">
                  No traces match the selected filters
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </SpatialCard>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <KpiCard title="Total Traces" value={traces.length.toLocaleString()} icon={<Activity className="text-muted" />} />
        <KpiCard title="Completed" value={traces.filter((t) => t.status === "COMPLETED").length.toLocaleString()} icon={<CheckCircle className="text-emerald-400" />} />
        <KpiCard title="Blocked" value={traces.filter((t) => t.status === "BLOCKED").length.toLocaleString()} icon={<AlertCircle className="text-red-400" />} />
        <KpiCard title="Pending HITL" value={traces.filter((t) => t.status === "PENDING_HITL").length.toLocaleString()} icon={<Zap className="text-amber-400" />} />
      </div>

      {/* Execution Inspector Slide-over */}
      {selectedTrace && (
        <div className="fixed inset-0 z-50 flex items-end justify-end bg-black/50 p-3 backdrop-blur-md lg:p-6" onClick={closeInspector}>
          <div className="h-full w-full max-w-[90vw] lg:w-[70vw]" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-glass specular-border hud-corners relative flex h-full flex-col overflow-hidden rounded-2xl border border-white/[0.1] shadow-[0_40px_120px_-40px_rgba(0,0,0,1)]">
              {/* Header */}
              <div className="flex items-center justify-between p-4 border-b border-border-subtle flex-shrink-0">
                <div className="flex items-center gap-3">
                  <Activity className="w-5 h-5 text-primary" />
                  <div>
                    <p className="font-mono font-bold text-primary text-sm">{selectedTrace.trace.agent_name}</p>
                    <p className="font-mono text-xs text-muted">Trace ID: {selectedTrace.trace.id}</p>
                  </div>
                  <span className={`status-badge ${STATUS_CONFIG[selectedTrace.trace.status]?.bg} ${STATUS_CONFIG[selectedTrace.trace.status]?.border} ${STATUS_CONFIG[selectedTrace.trace.status]?.color} px-2 py-0.5 rounded text-xs`}>
                    {STATUS_CONFIG[selectedTrace.trace.status]?.label || selectedTrace.trace.status}
                  </span>
                </div>
                <button onClick={closeInspector} className="text-muted hover:text-primary p-1">
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Error message */}
              {errorMessage && (
                <div className="m-4 p-3 bg-red-400/10 border border-red-400/25 rounded-md text-red-400 text-xs font-mono flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  <span>{errorMessage}</span>
                </div>
              )}

              {/* Loading */}
              {loadingDetail && (
                <div className="flex-1 flex items-center justify-center">
                  <div className="animate-spin rounded-full border-4 border-border-subtle border-t-primary h-8 w-8" />
                </div>
              )}

              {/* Content */}
              {!loadingDetail && selectedTrace && (
                <div className="flex-1 flex flex-col overflow-hidden">
                  {/* Waterfall (Left) + JSON Inspector (Right) */}
                  <div className="flex-1 flex overflow-hidden">
                    {/* Left: Span Waterfall */}
                    <div className="w-full lg:w-1/2 border-r border-border-subtle flex flex-col overflow-hidden min-w-0">
                      <div className="p-4 border-b border-border-subtle bg-surface/50 flex-shrink-0">
                        <h3 className="font-mono font-bold text-primary text-sm flex items-center gap-2">
                          <Code2 className="w-4 h-4" />
                          Execution Waterfall
                        </h3>
                        <p className="text-xs text-muted mt-1">{selectedTrace.spans.length} spans • {selectedTrace.trace.total_latency_ms}ms total</p>
                      </div>
                      <div className="flex-1 overflow-y-auto p-4">
                        {selectedTrace.spans.length === 0 ? (
                          <div className="text-center text-muted text-sm font-mono py-8">
                            No spans recorded for this trace
                          </div>
                        ) : (
                          <div className="space-y-4">
                            {selectedTrace.spans.map((span, index) => {
                              const typeConfig = SPAN_TYPE_CONFIG[span.span_type] || SPAN_TYPE_CONFIG.LLM_INFERENCE;
                              const statusConfig = SPAN_STATUS_CONFIG[span.status] || SPAN_STATUS_CONFIG.OK;
                              const maxLatency = getMaxLatency(selectedTrace.spans);
                              const isSelected = selectedSpan?.id === span.id;

                              return (
                                <div
                                  key={span.id}
                                  className={`group relative p-3 rounded-md border transition-all ${
                                    isSelected
                                      ? "bg-primary/5 border-primary/30 shadow-lg"
                                      : "bg-surface-hover border-border-subtle hover:bg-surface-hover"
                                  }`}
                                  onClick={() => setSelectedSpan(span)}
                                >
                                  <div className="flex items-start gap-3">
                                    <div className="flex flex-col items-center min-w-[60px]">
                                      <span className={`font-mono text-xs ${typeConfig.color} ${typeConfig.bg} px-1.5 py-0.5 rounded text-center`}>
                                        {typeConfig.label}
                                      </span>
                                      <span className="font-mono text-xs text-muted mt-1">#{span.step_index}</span>
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center justify-between gap-2 mb-1">
                                        <h4 className="font-mono text-sm text-primary truncate">{span.name}</h4>
                                        <span className={`font-mono text-xs ${statusConfig.color} ${statusConfig.bg} px-1.5 py-0.5 rounded`}>
                                          {statusConfig.label}
                                        </span>
                                      </div>
                                      <div className="flex items-center gap-3 text-xs text-muted font-mono">
                                        <span>{span.model_or_server}</span>
                                        <span>{span.latency_ms}ms</span>
                                        {span.tokens_used > 0 && <span>{span.tokens_used} tok</span>}
                                        {span.cost_usd > 0 && <span>${span.cost_usd.toFixed(6)}</span>}
                                      </div>
                                      {/* Latency bar */}
                                      <div className="mt-2">
                                        {renderLatencyBar(span.latency_ms, maxLatency)}
                                      </div>
                                    </div>
                                  </div>
                                  {/* Guardrail reason indicator */}
                                  {span.guardrail_reason && (
                                    <div className="mt-2 p-2 bg-amber-400/10 border border-amber-400/25 rounded text-xs font-mono text-amber-400">
                                      ⚠ {span.guardrail_reason}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Right: JSON Inspector */}
                    <div className="w-full lg:w-1/2 flex flex-col overflow-hidden min-w-0">
                      <div className="p-4 border-b border-border-subtle bg-surface/50 flex-shrink-0">
                        <h3 className="font-mono font-bold text-primary text-sm flex items-center gap-2">
                          <FileText className="w-4 h-4" />
                          Span Inspector
                        </h3>
                        <p className="text-xs text-muted mt-1">
                          {selectedSpan
                            ? `Viewing: ${selectedSpan.name} (${selectedSpan.id})`
                            : "Click a span to inspect payload"}
                        </p>
                      </div>
                      <div className="flex-1 overflow-auto p-4">
                        {selectedSpan ? (
                          <div className="space-y-6">
                            <div>
                              <h4 className="text-xs font-mono text-muted mb-2 flex items-center gap-2">
                                <FileText className="w-3 h-3" />
                                Input Payload
                              </h4>
                              <pre className="max-h-[300px] overflow-auto rounded-lg border border-white/[0.08] bg-black/50 p-4 font-mono text-[11px] leading-relaxed text-white/70">
                                <JsonBlock json={formatJson(selectedSpan.input_payload)} />
                              </pre>
                            </div>
                            <div>
                              <h4 className="text-xs font-mono text-muted mb-2 flex items-center gap-2">
                                <Code2 className="w-3 h-3" />
                                Output Payload
                              </h4>
                              <pre className="max-h-[300px] overflow-auto rounded-lg border border-white/[0.08] bg-black/50 p-4 font-mono text-[11px] leading-relaxed text-white/70">
                                <JsonBlock json={formatJson(selectedSpan.output_payload)} />
                              </pre>
                            </div>
                            {selectedSpan.guardrail_reason && (
                              <div className="bg-amber-400/10 border border-amber-400/25 rounded-md p-4">
                                <h4 className="text-xs font-mono text-amber-400 mb-2 flex items-center gap-2">
                                  <AlertTriangle className="w-3 h-3" />
                                  Guardrail Reason
                                </h4>
                                <p className="text-xs font-mono text-amber-400 whitespace-pre-wrap">{selectedSpan.guardrail_reason}</p>
                              </div>
                            )}
                          </div>
                        ) : (
                          <div className="flex-1 flex items-center justify-center text-muted text-sm font-mono">
                            Select a span from the waterfall to view its input/output payloads and guardrail details.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function KpiCard({
  title,
  value,
  icon,
}: {
  title: string;
  value: string;
  icon: ReactNode;
}) {
  return (
    <SpatialCard className="p-4">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-white/40">{title}</span>
        <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04]">{icon}</div>
      </div>
      <div className="font-mono text-2xl font-bold tabular-nums text-white">{value}</div>
    </SpatialCard>
  );
}

const JSON_TOKEN =
  /("(?:\\.|[^"\\])*")(\s*:)?|\b(?:true|false)\b|\bnull\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;

function JsonBlock({ json }: { json: string }) {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  JSON_TOKEN.lastIndex = 0;

  while ((match = JSON_TOKEN.exec(json)) !== null) {
    if (match.index > cursor) nodes.push(json.slice(cursor, match.index));
    const token = match[0];
    if (match[1]) {
      nodes.push(
        <span key={`k${key++}`} className="json-key">
          {match[1]}
        </span>,
      );
      if (match[2]) nodes.push(match[2]);
    } else if (token === "true" || token === "false") {
      nodes.push(
        <span key={`b${key++}`} className="json-boolean">
          {token}
        </span>,
      );
    } else if (token === "null") {
      nodes.push(
        <span key={`n${key++}`} className="json-null">
          {token}
        </span>,
      );
    } else {
      nodes.push(
        <span key={`v${key++}`} className="json-number">
          {token}
        </span>,
      );
    }
    cursor = match.index + token.length;
  }
  nodes.push(json.slice(cursor));
  return <>{nodes}</>;
}
