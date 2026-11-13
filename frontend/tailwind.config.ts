import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#09090B",
        surface: "#111113",
        "surface-hover": "#18181B",
        border: {
          subtle: "#27272A",
          focus: "#52525B",
        },
        text: {
          primary: "#FAFAFA",
          secondary: "#A1A1AA",
          muted: "#71717A",
        },
        status: {
          healthy: {
            text: "#34D399",
            bg: "rgba(16, 185, 129, 0.1)",
            border: "rgba(16, 185, 129, 0.25)",
          },
          pending: {
            text: "#FBBF24",
            bg: "rgba(245, 158, 11, 0.1)",
            border: "rgba(245, 158, 11, 0.25)",
          },
          blocked: {
            text: "#F87171",
            bg: "rgba(239, 68, 68, 0.1)",
            border: "rgba(239, 68, 68, 0.25)",
          },
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains-mono)", "ui-monospace", "monospace"],
      },
      fontVariantNumeric: ["tabular-nums"],
    },
  },
  plugins: [],
};

export default config;