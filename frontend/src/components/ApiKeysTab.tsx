"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, Trash2, Copy, Check, Loader2, AlertCircle, Terminal, FileText, Key as KeyIcon } from "lucide-react";
import { api } from "@/lib/api";
import SpatialCard from "@/components/SpatialCard";
import { ApiError } from "@/lib/errors";
import type { APIKey, APIKeyCreateResponse } from "@/types/aegis";

export default function ApiKeysTab() {
  const [apiKeys, setApiKeys] = useState<APIKey[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyRaw, setNewKeyRaw] = useState<string | null>(null);
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null);
  const [showSkeleton, setShowSkeleton] = useState(false);

  const loadApiKeys = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const keys = await api.apiKeys();
      setApiKeys(keys);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to load API keys";
      setErrorMessage(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadApiKeys();
  }, [loadApiKeys]);

  const handleCreateKey = async () => {
    if (!newKeyName.trim()) {
      setErrorMessage("Please enter a name for the API key");
      return;
    }

    setCreating(true);
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const response = await api.createApiKey({ name: newKeyName.trim() });
      setNewKeyRaw(response.raw_key);
      setNewKeyName("");
      setSuccessMessage(`API key created! Raw key shown once below.`);
      await loadApiKeys();
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : (err instanceof Error ? err.message : "Failed to create API key");
      setErrorMessage(msg);
    } finally {
      setCreating(false);
    }
  };

  const handleRevokeKey = async (keyId: string) => {
    if (!confirm("Are you sure you want to revoke this API key? This action cannot be undone.")) {
      return;
    }

    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      await api.deleteApiKey(keyId);
      setSuccessMessage("API key revoked successfully");
      await loadApiKeys();
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.message : (err instanceof Error ? err.message : "Failed to revoke API key");
      setErrorMessage(msg);
    }
  };

  const handleCopyKey = (key: string) => {
    navigator.clipboard.writeText(key);
    setCopiedKeyId(key);
    setTimeout(() => setCopiedKeyId(null), 2000);
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const getStatusBadge = (isActive: boolean) => (
    <span className={`px-2 py-0.5 rounded text-xs font-mono ${isActive ? "bg-emerald-400/10 text-emerald-400 border border-emerald-400/25" : "bg-red-400/10 text-red-400 border border-red-400/25"}`}>
      {isActive ? "Active" : "Revoked"}
    </span>
  );

  const activeCount = apiKeys.filter((key) => key.is_active).length;
  const revokedCount = apiKeys.length - activeCount;

  return (
    <div className="space-y-6">
      {/* Header + live key statistics */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <KeyIcon className="h-6 w-6 text-emerald-300" />
            <h2 className="font-mono text-xl font-bold text-white">API Keys & SDK</h2>
          </div>
          <p className="mt-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-white/30">
            Bearer credentials for external agent runtimes
          </p>
        </div>
        <div className="flex items-center gap-2">
          <KeyStat label="Total" value={apiKeys.length} tone="text-white/70 border-white/10 bg-white/[0.03]" />
          <KeyStat label="Active" value={activeCount} tone="text-emerald-300 border-emerald-400/25 bg-emerald-400/10" />
          <KeyStat label="Revoked" value={revokedCount} tone="text-red-300 border-red-400/25 bg-red-400/10" />
        </div>
      </div>

      {errorMessage && (
        <div className="flex items-center gap-2 rounded-lg border border-red-400/25 bg-red-400/10 p-3 font-mono text-xs text-red-400 backdrop-blur-xl">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{errorMessage}</span>
          <button onClick={() => setErrorMessage(null)} className="ml-auto text-white/40 hover:text-white">×</button>
        </div>
      )}

      {successMessage && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-400/25 bg-emerald-400/10 p-3 font-mono text-xs text-emerald-400 backdrop-blur-xl">
          <Check className="h-4 w-4 shrink-0" />
          <span>{successMessage}</span>
          <button onClick={() => setSuccessMessage(null)} className="ml-auto text-white/40 hover:text-white">×</button>
        </div>
      )}

      {/* One-time raw key */}
      {newKeyRaw && (
        <SpatialCard glow="emerald" tilt={false} className="p-5 animate-slide-down">
          <h3 className="mb-3 flex items-center gap-2 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-300">
            <Check className="h-4 w-4" />
            New API key generated — shown once
          </h3>
          <div className="flex items-center gap-3 overflow-x-auto rounded-lg border border-emerald-400/20 bg-black/60 p-3 font-mono text-xs text-emerald-300">
            <code className="whitespace-nowrap">{newKeyRaw}</code>
            <button
              onClick={() => handleCopyKey(newKeyRaw)}
              className="ml-auto shrink-0 rounded border border-emerald-400/25 bg-emerald-400/10 px-2 py-1 text-emerald-300 transition-colors hover:bg-emerald-400/20"
              aria-label="Copy API key"
            >
              {copiedKeyId === newKeyRaw ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </button>
          </div>
          <p className="mt-2 font-mono text-[11px] text-white/35">
            Save this key now — it will not be shown again. Use it with the <code className="text-emerald-300">AegisClient</code> Python SDK or as a bearer token.
          </p>
        </SpatialCard>
      )}

      {/* Create + environment */}
      <div className="grid items-stretch gap-6 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <SpatialCard tilt={false} className="h-full p-5" contentClassName="flex h-full flex-col">
          <h3 className="mb-4 flex items-center gap-2 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-white/45">
            <Plus className="h-4 w-4 text-emerald-300" />
            Create new API key
          </h3>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1">
              <label className="mb-1.5 block font-mono text-[10px] uppercase tracking-[0.16em] text-white/35">Key name</label>
              <input
                type="text"
                className="w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5 text-sm text-white placeholder:text-white/25 outline-none transition-colors focus:border-emerald-400/40"
                placeholder="e.g., production-agent, ci-pipeline, dev-laptop"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                disabled={creating}
              />
            </div>
            <button
              onClick={handleCreateKey}
              disabled={creating || !newKeyName.trim()}
              className="flex items-center justify-center gap-2 rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-4 py-2.5 font-mono text-xs font-medium uppercase tracking-[0.12em] text-emerald-300 transition-colors hover:bg-emerald-400/20 disabled:opacity-40"
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              <span>{creating ? "Creating..." : "Generate key"}</span>
            </button>
          </div>

          <ul className="mt-auto space-y-2 pt-6">
            {[
              "Raw keys are returned exactly once — the gateway stores only the SHA-256 prefix.",
              "Send as Authorization: Bearer aegis_live_… on every ingest or intercept call.",
              "Revoking takes effect on the next request; no restart required.",
            ].map((line) => (
              <li key={line} className="flex items-start gap-2 font-mono text-[11px] leading-relaxed text-white/35">
                <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400/70" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </SpatialCard>

        <SpatialCard tilt={false} className="h-full p-5" contentClassName="flex h-full flex-col">
          <h3 className="mb-4 flex items-center gap-2 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-white/45">
            <FileText className="h-4 w-4 text-emerald-300" />
            Environment setup
          </h3>
          <div className="overflow-x-auto rounded-lg border border-white/[0.08] bg-black/50 p-4 font-mono text-[11px] leading-relaxed text-white/60">
            <pre>{`# .env
AEGIS_API_KEY=aegis_live_xxxxxxxxxxxx...
AEGIS_BASE_URL=http://localhost:8000

# For production PostgreSQL
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/aegis
`}</pre>
          </div>
          <p className="mt-auto pt-4 font-mono text-[11px] leading-relaxed text-white/30">
            Point <code className="text-white/55">AEGIS_BASE_URL</code> at your gateway; the SDK appends the versioned API prefix itself.
          </p>
        </SpatialCard>
      </div>

      {/* Issued credentials */}
      <SpatialCard tilt={false} className="overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-3">
          <h3 className="flex items-center gap-2 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-white/45">
            <KeyIcon className="h-4 w-4 text-emerald-300/70" />
            Issued credentials
          </h3>
          <span className="font-mono text-[10px] uppercase tracking-[0.16em] text-white/25">
            {apiKeys.length} {apiKeys.length === 1 ? "key" : "keys"} · {activeCount} active
          </span>
        </div>
        {loading ? (
          <div className="p-10 text-center">
            <Loader2 className="mx-auto mb-2 h-6 w-6 animate-spin text-white/40" />
            <p className="font-mono text-sm text-white/40">Loading API keys...</p>
          </div>
        ) : apiKeys.length === 0 ? (
          <div className="p-10 text-center">
            <KeyIcon className="mx-auto mb-4 h-12 w-12 text-white/20" />
            <h3 className="mb-2 font-mono font-medium text-white/80">No API keys yet</h3>
            <p className="text-sm text-white/40">Create your first API key above to authenticate external agents.</p>
          </div>
        ) : (
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-white/[0.08] bg-white/[0.02]">
                <th className="px-5 py-3 font-mono text-[10px] uppercase tracking-[0.14em] text-white/40">Prefix</th>
                <th className="px-5 py-3 font-mono text-[10px] uppercase tracking-[0.14em] text-white/40">Name</th>
                <th className="px-5 py-3 text-center font-mono text-[10px] uppercase tracking-[0.14em] text-white/40">Status</th>
                <th className="px-5 py-3 text-center font-mono text-[10px] uppercase tracking-[0.14em] text-white/40">Created</th>
                <th className="px-5 py-3 text-center font-mono text-[10px] uppercase tracking-[0.14em] text-white/40">Last used</th>
                <th className="px-5 py-3 text-center font-mono text-[10px] uppercase tracking-[0.14em] text-white/40">Actions</th>
              </tr>
            </thead>
            <tbody>
              {apiKeys.map((key) => (
                <tr key={key.id} className="border-b border-white/[0.05] transition-colors last:border-0 hover:bg-white/[0.04]">
                  <td className="px-5 py-3 font-mono text-xs text-white/60">{key.key_prefix}</td>
                  <td className="px-5 py-3 text-sm text-white/85">{key.name}</td>
                  <td className="px-5 py-3 text-center">{getStatusBadge(key.is_active)}</td>
                  <td className="px-5 py-3 text-center font-mono text-[11px] text-white/40">{formatDate(key.created_at)}</td>
                  <td className="px-5 py-3 text-center font-mono text-[11px] text-white/40">
                    {key.last_used_at ? formatDate(key.last_used_at) : "Never"}
                  </td>
                  <td className="px-5 py-3 text-center">
                    <div className="flex items-center justify-center gap-2">
                      {key.is_active && (
                        <button
                          onClick={() => handleRevokeKey(key.id)}
                          className="flex items-center gap-1 rounded border border-red-400/25 bg-red-400/10 px-3 py-1.5 font-mono text-xs font-medium text-red-400 transition-colors hover:bg-red-400/20"
                        >
                          <Trash2 className="h-3 w-3" />
                          Revoke
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SpatialCard>

      {/* SDK + enforcement path */}
      <div className="grid items-stretch gap-6 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
        <SpatialCard tilt={false} className="p-5" contentClassName="flex h-full flex-col">
          <h3 className="mb-4 flex items-center gap-2 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-white/45">
            <Terminal className="h-4 w-4 text-emerald-300" />
            Python SDK usage
          </h3>
          <div className="overflow-x-auto rounded-lg border border-white/[0.08] bg-black/50 p-4 font-mono text-[11px] leading-relaxed text-white/60">
            <pre>{`# pip install httpx
from aegis_sdk import AegisClient

# Initialize client with your API key
client = AegisClient(
    api_key="aegis_live_xxxxxxxxxxxx...",
    base_url="http://localhost:8000"
)

# Use as a decorator to guard tool calls
@client.guard_tool("postgres-mcp", "execute_query")
def run_query(sql: str):
    # Your actual tool execution logic here
    return database.execute(sql)

# Or use context manager
with client.intercept("stripe-billing-mcp", "create_refund") as ctx:
    ctx.set_input({"amount": 45000, "currency": "usd"})
    result = stripe.Refund.create(amount=45000)
    ctx.set_output(result)
`}</pre>
          </div>
          <p className="mt-auto pt-4 font-mono text-[11px] leading-relaxed text-white/30">
            Both helpers call <code className="text-white/55">POST /api/v1/proxy/intercept</code> before your body runs, so a blocked
            or HITL-paused call never reaches the tool.
          </p>
        </SpatialCard>

        <SpatialCard tilt={false} className="p-5" contentClassName="flex h-full flex-col">
          <h3 className="mb-4 flex items-center gap-2 font-mono text-[10px] font-bold uppercase tracking-[0.18em] text-white/45">
            <AlertCircle className="h-4 w-4 text-emerald-300" />
            Enforcement path
          </h3>
          <ul className="space-y-3">
            {[
              { method: "POST", path: "/api/v1/proxy/intercept", note: "Pre-execution guardrail verdict" },
              { method: "POST", path: "/api/v1/ingest/span", note: "Span + trace accounting" },
              { method: "POST", path: "/api/v1/mcp/{server}/rpc", note: "JSON-RPC tool gateway" },
              { method: "POST", path: "/api/v1/otlp/v1/traces", note: "OpenTelemetry ingest" },
            ].map((route) => (
              <li key={route.path} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                <div className="flex items-center gap-2 font-mono text-[10px]">
                  <span className="rounded border border-emerald-400/25 bg-emerald-400/10 px-1.5 py-0.5 text-emerald-300">
                    {route.method}
                  </span>
                  <code className="truncate text-white/60">{route.path}</code>
                </div>
                <p className="mt-1 font-mono text-[10px] uppercase tracking-[0.12em] text-white/25">{route.note}</p>
              </li>
            ))}
          </ul>
          <p className="mt-auto pt-4 font-mono text-[11px] leading-relaxed text-white/30">
            Every request is scoped to your <code className="text-white/55">org_id</code> and rate-limited per operator.
          </p>
        </SpatialCard>
      </div>
    </div>
  );
}

function KeyStat({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className={`flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-[10px] uppercase tracking-[0.14em] ${tone}`}>
      <span className="text-white/35">{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}
