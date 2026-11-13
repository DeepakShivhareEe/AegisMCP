"use client";

import { useCallback, useRef, type CSSProperties, type ReactNode } from "react";
import clsx from "clsx";

type GlowTone = "neutral" | "emerald" | "amber" | "red" | "blue";

const GLOW_COLOR: Record<GlowTone, string> = {
  neutral: "rgba(255, 255, 255, 0.08)",
  emerald: "rgba(16, 185, 129, 0.20)",
  amber: "rgba(245, 158, 11, 0.18)",
  red: "rgba(239, 68, 68, 0.18)",
  blue: "rgba(96, 165, 250, 0.16)",
};

const GLOW_BORDER: Record<GlowTone, string> = {
  neutral: "border-white/[0.08]",
  emerald: "border-emerald-400/20",
  amber: "border-amber-400/20",
  red: "border-red-400/20",
  blue: "border-blue-400/20",
};

interface SpatialCardProps {
  children: ReactNode;
  className?: string;
  /** Layout classes for the content wrapper (flex/grid/gap live here, not on the card root). */
  contentClassName?: string;
  glow?: GlowTone;
  /** Set false for large data tables where tilt would hurt reading. */
  tilt?: boolean;
  spotlight?: boolean;
  onClick?: () => void;
  ariaLabel?: string;
}

export default function SpatialCard({
  children,
  className = "",
  contentClassName = "",
  glow = "neutral",
  tilt = true,
  spotlight = true,
  onClick,
  ariaLabel,
}: SpatialCardProps) {
  const cardRef = useRef<HTMLDivElement | null>(null);

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!tilt && !spotlight) return;
      const element = cardRef.current;
      if (!element) return;
      const bounds = element.getBoundingClientRect();
      const x = event.clientX - bounds.left;
      const y = event.clientY - bounds.top;
      const px = x / Math.max(bounds.width, 1);
      const py = y / Math.max(bounds.height, 1);

      element.style.setProperty("--mx", `${x.toFixed(1)}px`);
      element.style.setProperty("--my", `${y.toFixed(1)}px`);
      element.style.setProperty("--spot", "1");

      if (tilt) {
        const rotateY = (px - 0.5) * 7;
        const rotateX = (0.5 - py) * 7;
        element.style.setProperty("--ry", `${rotateY.toFixed(2)}deg`);
        element.style.setProperty("--rx", `${rotateX.toFixed(2)}deg`);
        element.style.setProperty("--scale", "1.008");
      }
    },
    [spotlight, tilt],
  );

  const handlePointerLeave = useCallback(() => {
    const element = cardRef.current;
    if (!element) return;
    element.style.setProperty("--rx", "0deg");
    element.style.setProperty("--ry", "0deg");
    element.style.setProperty("--scale", "1");
    element.style.setProperty("--spot", "0");
  }, []);

  const style: CSSProperties = {
    transform:
      "perspective(1000px) rotateX(var(--rx, 0deg)) rotateY(var(--ry, 0deg)) scale3d(var(--scale, 1), var(--scale, 1), var(--scale, 1))",
    transition: "transform 260ms cubic-bezier(0.22, 1, 0.36, 1)",
    transformStyle: "preserve-3d",
    ["--glow" as string]: GLOW_COLOR[glow],
  };

  return (
    <div
      ref={cardRef}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      aria-label={ariaLabel}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      onPointerMove={handlePointerMove}
      onPointerLeave={handlePointerLeave}
      style={style}
      className={clsx(
        "group relative overflow-hidden rounded-xl border bg-zinc-950/[0.62] backdrop-blur-xl",
        "shadow-[0_1px_0_0_rgba(255,255,255,0.06)_inset,0_24px_60px_-30px_rgba(0,0,0,0.9)]",
        "transition-colors duration-300",
        GLOW_BORDER[glow],
        onClick && "cursor-pointer",
        className,
      )}
    >
      {/* top chrome highlight */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/25 to-transparent" />

      {/* cursor-following specular spotlight */}
      {spotlight && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[var(--spot,0)] transition-opacity duration-300"
          style={{
            background:
              "radial-gradient(340px circle at var(--mx, 50%) var(--my, 0%), var(--glow, rgba(255,255,255,0.08)), transparent 62%)",
          }}
        />
      )}

      {/* inner hairline for glass depth */}
      <div className="pointer-events-none absolute inset-0 rounded-xl ring-1 ring-inset ring-white/[0.04]" />

      <div className={clsx("relative", contentClassName)}>{children}</div>
    </div>
  );
}
