"use client";

import { useState, useEffect } from "react";
import { Shield, AlertCircle, CheckCircle, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import SpatialCard from "@/components/SpatialCard";
import { ApiError } from "@/lib/errors";
import type { MCPServer } from "@/types/aegis";

const MODE_CONFIG: Record<string, { color: string; label: string }> = {
  ALLOW_ALL: { color: "text-emerald-400", label: "Allow All" },
  READ_ONLY: { color: "text-secondary", label: "Read Only" },
  HITL_REQUIRED: { color: "text-amber-400", label: "HITL Required" },
  STRICT_BLOCK: { color: "text-red-400", label: "Strict Block" },
};

export default function PolicyFirewall() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const [form, setForm] = useState<{
    permission_mode: string;
    max_cost_usd_per_run: string;
    max_steps_per_run: string;
    blocked_patterns: string;
  }>({
    permission_mode: "ALLOW_ALL",
    max_cost_usd_per_run: "0.50",
    max_steps_per_run: "15",
    blocked_patterns: "",
  });

  const loadServers = async () => {
    try {
      setLoading(true);
      const data = await api.mcpServers();
      setServers(data);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load MCP servers";
      setErrorMessage(msg);
      console.error("Failed to load MCP servers:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadServers();
  }, []);

  const startEdit = (server: MCPServer) => {
    setForm({
      permission_mode: server.permission_mode,
      max_cost_usd_per_run: server.max_cost_usd_per_run.toString(),
      max_steps_per_run: server.max_steps_per_run.toString(),
      blocked_patterns: server.blocked_patterns.join("\n"),
    });
    setEditingId(server.id);
    setErrorMessage(null);
    setSuccessMessage(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setErrorMessage(null);
  };

  const saveEdit = async () => {
    if (!editingId) return;

    const maxCost = parseFloat(form.max_cost_usd_per_run);
    if (isNaN(maxCost) || maxCost < 0) {
      setErrorMessage("Max cost must be a positive number.");
      return;
    }

    const maxSteps = parseInt(form.max_steps_per_run, 10);
    if (isNaN(maxSteps) || maxSteps < 1) {
      setErrorMessage("Max steps must be an integer of at least 1.");
      return;
    }

    const blockedPatterns = form.blocked_patterns
      .split("\n")
      .map((p) => p.trim())
      .filter(Boolean);

    setSaving(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const updated = await api.patchMcpServer(editingId, {
        permission_mode: form.permission_mode,
        max_cost_usd_per_run: maxCost,
        max_steps_per_run: maxSteps,
        blocked_patterns: blockedPatterns,
      });

      setServers((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      setEditingId(null);
      setSuccessMessage(`Updated policy for ${updated.name}.`);
    } catch (err: unknown) {
      let msg = "Failed to update MCP server";
      if (err instanceof ApiError) {
        msg = err.message;
      } else if (err instanceof Error) {
        msg = err.message;
      }
      setErrorMessage(msg);
      console.error("Failed to update MCP server:", err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="w-5 h-5 text-muted" />
          <h2 className="text-lg font-mono font-bold text-primary">MCP Policy Firewall</h2>
        </div>
      </div>

      {errorMessage && (
        <div className="flex items-center gap-2 p-3 bg-red-400/10 border border-red-400/25 rounded-md text-red-400 text-xs font-mono">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage(null)} className="ml-auto text-muted hover:text-primary">
            ×
          </button>
        </div>
      )}

      {successMessage && (
        <div className="flex items-center gap-2 p-3 bg-emerald-400/10 border border-emerald-400/25 rounded-md text-emerald-400 text-xs font-mono">
          <CheckCircle className="w-4 h-4 shrink-0" />
          <span>{successMessage}</span>
          <button onClick={() => setSuccessMessage(null)} className="ml-auto text-muted hover:text-primary">
            ×
          </button>
        </div>
      )}

      {loading ? (
        <div className="bg-surface border border-border-subtle rounded-md p-8 text-center">
          <Loader2 className="w-6 h-6 text-muted animate-spin mx-auto mb-2" />
          <p className="text-sm text-muted font-mono">Loading MCP servers...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {servers.length === 0 && (
            <div className="md:col-span-2 lg:col-span-4 bg-surface border border-border-subtle rounded-md p-8 text-center">
              <Shield className="w-8 h-8 text-muted mx-auto mb-3 opacity-50" />
              <h3 className="font-mono font-medium text-primary mb-1">No MCP servers registered</h3>
              <p className="text-sm text-muted">
                Register an MCP server before configuring its guardrail policy.
              </p>
            </div>
          )}

          {servers.map((server) => {
            const isEditing = editingId === server.id;
            return (
              <SpatialCard
                key={server.id}
                glow={
                  server.permission_mode === "STRICT_BLOCK"
                    ? "red"
                    : server.permission_mode === "HITL_REQUIRED"
                      ? "amber"
                      : server.permission_mode === "READ_ONLY"
                        ? "blue"
                        : "emerald"
                }
                className="h-full p-5"
                contentClassName="flex h-full flex-col justify-between"
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <div className="font-mono font-bold text-sm text-primary">{server.name}</div>
                      <div className="text-xs text-muted mono">{server.id}</div>
                    </div>
                    <span className="text-xs font-medium mono px-2 py-1 rounded border border-border-subtle bg-surface-hover">
                      {server.status}
                    </span>
                  </div>

                  {isEditing ? (
                    <div className="space-y-3 mb-4 text-xs font-mono">
                      <div>
                        <label className="text-muted block mb-1">Permission Mode</label>
                        <select
                          value={form.permission_mode}
                          onChange={(e) => setForm({ ...form, permission_mode: e.target.value })}
                          className="w-full bg-canvas border border-border-subtle rounded px-2 py-1 text-primary focus:border-border-focus outline-none"
                        >
                          <option value="ALLOW_ALL">Allow All</option>
                          <option value="READ_ONLY">Read Only</option>
                          <option value="HITL_REQUIRED">HITL Required</option>
                          <option value="STRICT_BLOCK">Strict Block</option>
                        </select>
                      </div>

                      <div>
                        <label className="text-muted block mb-1">Max Cost/Run ($)</label>
                        <input
                          type="number"
                          step="0.05"
                          min="0"
                          value={form.max_cost_usd_per_run}
                          onChange={(e) => setForm({ ...form, max_cost_usd_per_run: e.target.value })}
                          className="w-full bg-canvas border border-border-subtle rounded px-2 py-1 text-primary focus:border-border-focus outline-none"
                        />
                      </div>

                      <div>
                        <label className="text-muted block mb-1">Max Steps</label>
                        <input
                          type="number"
                          min="1"
                          value={form.max_steps_per_run}
                          onChange={(e) => setForm({ ...form, max_steps_per_run: e.target.value })}
                          className="w-full bg-canvas border border-border-subtle rounded px-2 py-1 text-primary focus:border-border-focus outline-none"
                        />
                      </div>

                      <div>
                        <label className="text-muted block mb-1">Blocked Patterns (1/line)</label>
                        <textarea
                          rows={3}
                          value={form.blocked_patterns}
                          onChange={(e) => setForm({ ...form, blocked_patterns: e.target.value })}
                          className="w-full bg-canvas border border-border-subtle rounded px-2 py-1 text-primary focus:border-border-focus outline-none resize-none"
                        />
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-3 mb-4">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted">Transport</span>
                        <span className="text-xs text-secondary mono">{server.transport}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted">Permission Mode</span>
                        <span className={`text-xs font-medium mono ${MODE_CONFIG[server.permission_mode]?.color || "text-secondary"}`}>
                          {MODE_CONFIG[server.permission_mode]?.label || server.permission_mode}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted">Max Cost/Run</span>
                        <span className="text-xs text-secondary mono tabular-nums">
                          ${server.max_cost_usd_per_run.toFixed(2)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted">Max Steps</span>
                        <span className="text-xs text-secondary mono tabular-nums">{server.max_steps_per_run}</span>
                      </div>
                      {server.blocked_patterns.length > 0 && (
                        <div>
                          <span className="text-xs text-muted block mb-1">Blocked ({server.blocked_patterns.length})</span>
                          <div className="flex flex-wrap gap-1">
                            {server.blocked_patterns.slice(0, 3).map((p) => (
                              <span key={p} className="text-[10px] px-1.5 py-0.5 rounded bg-surface-hover border border-border-subtle text-muted mono">
                                {p}
                              </span>
                            ))}
                            {server.blocked_patterns.length > 3 && (
                              <span className="text-[10px] px-1.5 py-0.5 text-muted mono">
                                +{server.blocked_patterns.length - 3} more
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                <div className="flex items-center gap-2 mt-2">
                  {isEditing ? (
                    <>
                      <button
                        disabled={saving}
                        onClick={saveEdit}
                        className="flex-1 px-3 py-1.5 bg-emerald-400/10 border border-emerald-400/25 text-emerald-400 text-xs font-medium mono rounded hover:bg-emerald-400/20 disabled:opacity-50 transition-colors"
                      >
                        {saving ? "Saving..." : "Save"}
                      </button>
                      <button
                        disabled={saving}
                        onClick={cancelEdit}
                        className="px-3 py-1.5 bg-surface border border-border-subtle text-muted text-xs font-medium mono rounded hover:bg-surface-hover disabled:opacity-50 transition-colors"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      onClick={() => startEdit(server)}
                      className="w-full px-3 py-1.5 border border-border-subtle bg-surface-hover text-xs font-medium mono text-secondary hover:text-primary hover:border-border-focus transition-colors"
                    >
                      Edit Policy
                    </button>
                  )}
                </div>
              </SpatialCard>
            );
          })}
        </div>
      )}

      <SpatialCard tilt={false} className="p-4">
        <h3 className="mb-3 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-white/45">Guardrail Rules Reference</h3>
        <div className="flex flex-wrap gap-2">
          {["DROP TABLE", "DELETE FROM", "TRUNCATE", "rm -rf", "sk_live_", "ghp_", "sudo ", "/etc/"].map((pattern) => (
            <span key={pattern} className="px-2.5 py-1 rounded bg-surface-hover border border-border-subtle text-xs text-muted mono">
              {pattern}
            </span>
          ))}
        </div>
      </SpatialCard>
    </div>
  );
}
