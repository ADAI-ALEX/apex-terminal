import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#0a0a0a",
        bg2: "#111111",
        bg3: "#161616",
        border: "#222222",
        gold: "#c9a84c",
        gold2: "#e8c97a",
        up: "#22c55e",
        down: "#ef4444",
        info: "#3b82f6",
        textmid: "#999999",
        textdim: "#555555",
      },
      fontFamily: {
        mono: ["DM Mono", "ui-monospace", "monospace"],
        sans: ["DM Sans", "ui-sans-serif", "system-ui"],
      },
    },
  },
  plugins: [],
};

export default config;
