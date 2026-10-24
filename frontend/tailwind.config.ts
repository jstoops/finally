import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: { DEFAULT: "#0d1117", panel: "#111722", raised: "#161d2a", hover: "#1b2433" },
        line: { DEFAULT: "#232c3b", strong: "#2f3a4d" },
        ink: { DEFAULT: "#d6dde8", muted: "#8592a6", faint: "#566175" },
        accent: { yellow: "#ecad0a", blue: "#209dd7", purple: "#753991" },
        up: { DEFAULT: "#22c55e", dim: "#14532d" },
        down: { DEFAULT: "#ef4444", dim: "#7f1d1d" },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
