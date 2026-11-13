"use client";

import { useState, useEffect, useCallback } from "react";
import { CheckCircle, AlertCircle, Clock, Loader2, FileText, Code2 } from "lucide-react";
import { api } from "@/lib/api";
import SpatialCard from "@/components/SpatialCard";
import { ApiError } from "@/lib/errors";
import type { AgentTrace, HitlPendingItem } from "@/types/aegis";

interface PendingItem {
  span: HitlPendingItem;
  traceId: string;
  traceAgentName: string;
}

export default function HitlQueue({ traces }: { traces: AgentTrace[] }) {
  const [pendingSpans, setPendingSpans] = useState<PendingItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [selectedSpan, setSelectedSpan] = useState<PendingItem | null>(null);
  const [showPayload, setShowPayload] = useState(false);

  const loadPendingSpans = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const response = await api.hitlPending();
      const items: PendingItem[] = response.items.map((item) => ({
        span: item,
        traceId: item.trace_id,
        traceAgentName: item.agent_name,
      }));
      setPendingSpans(items);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load pending spans";
      setErrorMessage(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPendingSpans();
    // Poll every 3 seconds for new HITL requests
    const interval = setInterval(loadPendingSpans, 3000);
    return () => clearInterval(interval);
  }, [loadPendingSpans]);

  const handleDecision = async (spanId: string, action: "APPROVE" | "REJECT") => {
    if (!spanId) {
      setErrorMessage("Cannot process decision: missing span identifier.");
      return;
    }

    setActionInProgress(spanId);
    setErrorMessage(null);
    setSuccessMessage(null);

    const note = action === "APPROVE" ? "Approved via HITL queue" : "Rejected via HITL queue";

    try {
      await api.spanDecision(spanId, { action, reviewer_note: note });
      setSuccessMessage(
        action === "APPROVE" ? `Span ${spanId} approved.` : `Span ${spanId} rejected.`
      );
      // Remove the span from pending state
      setPendingSpans((prev) => prev.filter((item) => item.span.span_id !== spanId));
      setSelectedSpan(null);
    } catch (err: unknown) {
      let msg = `Failed to ${action.toLowerCase()} span`;
      if (err instanceof ApiError) {
        msg = err.message;
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setErrorMessage(msg);
      console.error(`HITL ${action} failed:`, err);
    } finally {
      setActionInProgress(null);
    }
  };

  const formatJson = (obj: Record<string, any> | null) => {
    if (!obj) return "{}";
    return JSON.stringify(obj, null, 2);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-muted" />
          <h2 className="text-lg font-mono font-bold text-primary">HITL Approval Queue</h2>
          {pendingSpans.length > 0 && (
            <span className="ml-2 px-2 py-0.5 rounded-full text-xs font-mono bg-amber-400/20 text-amber-400 border border-amber-400/30">
              {pendingSpans.length} pending
            </span>
          )}
        </div>
      </div>

      {errorMessage && (
        <div className="flex items-center gap-2 p-3 bg-red-400/10 border border-red-400/25 rounded-md text-red-400 text-xs font-mono">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMessage}</span>
          <button
            onClick={() => setErrorMessage(null)}
            className="ml-auto text-muted hover:text-primary"
          >
            ×
          </button>
        </div>
      )}

      {successMessage && (
        <div className="flex items-center gap-2 p-3 bg-emerald-400/10 border border-emerald-400/25 rounded-md text-emerald-400 text-xs font-mono">
          <CheckCircle className="w-4 h-4 shrink-0" />
          <span>{successMessage}</span>
          <button
            onClick={() => setSuccessMessage(null)}
            className="ml-auto text-muted hover:text-primary"
          >
            ×
          </button>
        </div>
      )}

      {loading && pendingSpans.length === 0 ? (
        <div className="bg-surface border border-border-subtle rounded-md p-8 text-center">
          <Loader2 className="w-6 h-6 text-muted animate-spin mx-auto mb-2" />
          <p className="text-sm text-muted font-mono">Loading pending approvals...</p>
        </div>
      ) : pendingSpans.length === 0 ? (
        <div className="bg-surface border border-border-subtle rounded-md p-8 text-center">
          <div className="w-12 h-12 rounded-full bg-surface-hover flex items-center justify-center mx-auto mb-4">
            <CheckCircle className="w-6 h-6 text-emerald-400" />
          </div>
          <h3 className="font-mono font-medium text-primary mb-2">No pending approvals</h3>
          <p className="text-sm text-muted">All spans are approved or no active traces require HITL.</p>
        </div>
      ) : (
        <SpatialCard tilt={false} className="overflow-hidden">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-white/[0.08] bg-white/[0.02]">
                <th className="px-4 py-3 text-xs font-mono font-bold text-muted">Span ID</th>
                <th className="px-4 py-3 text-xs font-mono font-bold text-muted">Trace ID</th>
                <th className="px-4 py-3 text-xs font-mono font-bold text-muted">Agent</th>
                <th className="px-4 py-3 text-xs font-mono font-bold text-muted">Tool / Target</th>
                <th className="px-4 py-3 text-xs font-mono font-bold text-muted">Reason</th>
                <th className="px-4 py-3 text-center">Actions</th>
              </tr>
            </thead>
            <tbody>
              {pendingSpans.map(({ span, traceId, traceAgentName }) => {
                const isOperating = actionInProgress === span.span_id;
                return (
                  <tr
                    key={span.span_id}
                    className="cursor-pointer border-b border-white/[0.05] transition-colors last:border-0 hover:bg-white/[0.04]"
                    onClick={() => {
                      setSelectedSpan({ span, traceId, traceAgentName });
                      setShowPayload(true);
                    }}
                  >
                    <td className="px-4 py-3 mono text-sm text-secondary">{span.span_id}</td>
                    <td className="px-4 py-3 mono text-sm text-primary">{traceId}</td>
                    <td className="px-4 py-3 text-sm text-muted">{traceAgentName}</td>
                    <td className="px-4 py-3 text-xs text-secondary mono">{span.name}</td>
                    <td className="px-4 py-3 text-xs text-amber-400 mono max-w-xs truncate" title={span.guardrail_reason || "HITL approval required"}>
                      {span.guardrail_reason || "HITL approval required"}
                    </td>
                    <td className="px-4 py-3 text-center">
                      <div className="flex items-center justify-center gap-2">
                        <button
                          disabled={isOperating}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDecision(span.span_id, "APPROVE");
                          }}
                          className="px-3 py-1.5 bg-emerald-400/10 border border-emerald-400/25 text-emerald-400 text-xs font-medium mono rounded hover:bg-emerald-400/20 disabled:opacity-50 transition-colors"
                        >
                          {isOperating ? "Processing..." : "Approve"}
                        </button>
                        <button
                          disabled={isOperating}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDecision(span.span_id, "REJECT");
                          }}
                          className="px-3 py-1.5 bg-red-400/10 border border-red-400/25 text-red-400 text-xs font-medium mono rounded hover:bg-red-400/20 disabled:opacity-50 transition-colors"
                        >
                          {isOperating ? "Processing..." : "Reject"}
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </SpatialCard>
      )}

      {/* Payload Preview Modal */}
      {selectedSpan && showPayload && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setShowPayload(false)}>
          <div className="drawer-glass specular-border hud-corners relative flex max-h-[80vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-white/[0.1] shadow-[0_40px_120px_-40px_rgba(0,0,0,1)]" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-border-subtle">
              <div className="flex items-center gap-3">
                <Code2 className="w-5 h-5 text-muted" />
                <div>
                  <p className="font-mono font-bold text-primary text-sm">{selectedSpan.span.name}</p>
                  <p className="font-mono text-xs text-muted">Span ID: {selectedSpan.span.span_id}</p>
                </div>
              </div>
              <button
                onClick={() => setShowPayload(false)}
                className="text-muted hover:text-primary p-1"
              >
                ×
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              <div className="grid gap-6">
                <div>
                  <h4 className="text-xs font-mono text-muted mb-2 flex items-center gap-2">
                    <FileText className="w-3 h-3" />
                    Input Payload
                  </h4>
                  <pre className="bg-surface-hover border border-border-subtle rounded-md p-4 text-xs font-mono text-secondary overflow-x-auto max-h-96">
                    {formatJson(selectedSpan.span.input_payload)}
                  </pre>
                </div>
                {selectedSpan.span.guardrail_reason && (
                  <div className="bg-amber-400/10 border border-amber-400/25 rounded-md p-4">
                    <h4 className="text-xs font-mono text-amber-400 mb-2 flex items-center gap-2">
                      <AlertCircle className="w-3 h-3" />
                      Guardrail Reason
                    </h4>
                    <p className="text-xs font-mono text-amber-400">{selectedSpan.span.guardrail_reason}</p>
                  </div>
                )}
              </div>
            </div>
            <div className="flex justify-end gap-2 p-4 border-t border-border-subtle">
              <button
                onClick={() => {
                  setShowPayload(false);
                  handleDecision(selectedSpan.span.span_id, "REJECT");
                }}
                className="px-4 py-2 bg-red-400/10 border border-red-400/25 text-red-400 text-xs font-medium mono rounded hover:bg-red-400/20 transition-colors"
              >
                Reject
              </button>
              <button
                onClick={() => {
                  setShowPayload(false);
                  handleDecision(selectedSpan.span.span_id, "APPROVE");
                }}
                className="px-4 py-2 bg-emerald-400/10 border border-emerald-400/25 text-emerald-400 text-xs font-medium mono rounded hover:bg-emerald-400/20 transition-colors"
              >
                Approve
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}