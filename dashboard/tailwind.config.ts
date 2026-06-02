import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Driven by CSS variables (see globals.css) so themes can swap them.
        bg: "rgb(var(--c-bg) / <alpha-value>)",
        bg2: "rgb(var(--c-bg2) / <alpha-value>)",
        bg3: "rgb(var(--c-bg3) / <alpha-value>)",
        border: "rgb(var(--c-border) / <alpha-value>)",
        gold: "rgb(var(--c-gold) / <alpha-value>)",
        gold2: "rgb(var(--c-gold2) / <alpha-value>)",
        up: "rgb(var(--c-up) / <alpha-value>)",
        down: "rgb(var(--c-down) / <alpha-value>)",
        info: "rgb(var(--c-info) / <alpha-value>)",
        textmid: "rgb(var(--c-textmid) / <alpha-value>)",
        textdim: "rgb(var(--c-textdim) / <alpha-value>)",
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
