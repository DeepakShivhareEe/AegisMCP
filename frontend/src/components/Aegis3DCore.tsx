"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentTrace, MCPServer } from "@/types/aegis";
import {
  createSpatialScene,
  DEFAULT_NODES,
  type CoreTone,
  type SpatialNode,
  type SpatialSceneHandle,
} from "@/lib/spatialScene";

interface Aegis3DCoreProps {
  traces: AgentTrace[];
  servers: MCPServer[];
  pendingHitl: number;
  shockwaveSignal?: number;
  active?: boolean;
  className?: string;
}

const TONE_LABEL: Record<CoreTone, string> = {
  healthy: "CORE SECURE",
  alert: "HITL PAUSED",
  blocked: "THREAT CONTAINED",
};

const TONE_TEXT: Record<CoreTone, string> = {
  healthy: "text-emerald-400",
  alert: "text-amber-400",
  blocked: "text-red-400",
};

export default function Aegis3DCore({
  traces,
  servers,
  pendingHitl,
  shockwaveSignal = 0,
  active = true,
  className = "",
}: Aegis3DCoreProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const labelRefs = useRef<Array<HTMLDivElement | null>>([]);
  const sceneRef = useRef<SpatialSceneHandle | null>(null);
  const lastSignalRef = useRef(0);
  const [webglError, setWebglError] = useState(false);

  const nodes: SpatialNode[] = useMemo(() => {
    if (servers.length === 0) return DEFAULT_NODES;
    return servers.slice(0, 4).map((server) => ({
      name: server.name,
      status: server.status,
      permissionMode: server.permission_mode,
    }));
  }, [servers]);

  const tone: CoreTone = useMemo(() => {
    const blocked = traces.some(
      (trace) => trace.status === "BLOCKED" || trace.status === "LOOP_KILLED",
    );
    if (blocked) return "blocked";
    if (pendingHitl > 0) return "alert";
    return "healthy";
  }, [traces, pendingHitl]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const reducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    try {
      sceneRef.current = createSpatialScene({
        container,
        labelElements: labelRefs.current.filter(
          (element): element is HTMLDivElement => element !== null,
        ),
        reducedMotion,
      });
    } catch (error) {
      console.error("WebGL scene initialisation failed:", error);
      setWebglError(true);
      return;
    }

    const handle = sceneRef.current;
    handle.setNodes(nodes);
    return () => {
      handle.dispose();
      sceneRef.current = null;
    };
    // The scene is created once; later prop changes are pushed imperatively.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    sceneRef.current?.setNodes(nodes);
  }, [nodes]);

  useEffect(() => {
    sceneRef.current?.setTone(tone);
  }, [tone]);

  useEffect(() => {
    sceneRef.current?.setActive(active);
  }, [active]);

  useEffect(() => {
    if (!shockwaveSignal || shockwaveSignal === lastSignalRef.current) return;
    lastSignalRef.current = shockwaveSignal;
    sceneRef.current?.shockwave();
  }, [shockwaveSignal]);

  return (
    <div
      className={`relative overflow-hidden rounded-2xl border border-white/[0.08] bg-[radial-gradient(circle_at_50%_40%,rgba(16,185,129,0.10),rgba(5,5,7,0.9)_62%)] ${className}`}
    >
      <div className="pointer-events-none absolute inset-0 spatial-grid opacity-40" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/25 to-transparent" />

      <div className="relative flex items-center justify-between px-4 pt-3 text-[10px] font-mono uppercase tracking-[0.22em]">
        <span className="text-white/40">Aegis // Spatial Core</span>
        <span className={`flex items-center gap-2 ${TONE_TEXT[tone]}`}>
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
          </span>
          {TONE_LABEL[tone]}
        </span>
      </div>

      <div
        ref={containerRef}
        className="relative h-[320px] w-full sm:h-[360px]"
        aria-label="Live 3D visualisation of MCP servers orbiting the Aegis security core"
        role="img"
      >
        {webglError && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="h-40 w-40 rounded-full border border-emerald-400/30 bg-emerald-400/5 blur-[1px]" />
          </div>
        )}

        {nodes.map((node, index) => (
          <div
            key={`${node.name}-${index}`}
            ref={(element) => {
              labelRefs.current[index] = element;
            }}
            className="pointer-events-none absolute left-0 top-0 whitespace-nowrap rounded-md border border-white/10 bg-zinc-950/80 px-2 py-1 font-mono text-[10px] leading-tight text-white/70 shadow-[0_0_18px_rgba(0,0,0,0.55)] backdrop-blur-md"
            style={{ transform: "translate(-50%, -50%)", opacity: 0.6 }}
          >
            <span className="block text-white/85">{node.name}</span>
            <span className="text-[9px] uppercase tracking-[0.14em] text-white/40">
              {node.status} · {node.permissionMode.replaceAll("_", " ")}
            </span>
          </div>
        ))}
      </div>

      <div className="relative flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.06] px-4 py-2.5 text-[10px] font-mono text-white/40">
        <span>{nodes.length} MCP nodes · {traces.length} traces</span>
        <span className="flex items-center gap-3">
          <Legend color="bg-emerald-400" label="Secure" />
          <Legend color="bg-amber-400" label="HITL" />
          <Legend color="bg-red-400" label="Blocked" />
        </span>
      </div>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-1.5 w-1.5 rounded-full ${color}`} />
      {label}
    </span>
  );
}
