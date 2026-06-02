export type ThemeMode = "dark" | "light" | "auto";

const KEY = "apex.theme";

/** Auto = light during the day (07:00–19:00), dark at night. */
export function resolve(mode: ThemeMode): "dark" | "light" {
  if (mode === "auto") {
    const h = new Date().getHours();
    return h >= 7 && h < 19 ? "light" : "dark";
  }
  return mode;
}

export function getMode(): ThemeMode {
  if (typeof localStorage === "undefined") return "dark";
  return ((localStorage.getItem(KEY) as ThemeMode) || "dark");
}

export function applyTheme(mode: ThemeMode): void {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("theme-light", resolve(mode) === "light");
  try { localStorage.setItem(KEY, mode); } catch { /* ignore */ }
  window.dispatchEvent(new Event("apex-theme"));
}

/** Chart colours pulled from the active theme's CSS variables. */
export function chartColors() {
  const fallback = { bg: "#0a0a0a", text: "#9a9a9a", grid: "#1c1c21", border: "#2c2c32" };
  if (typeof window === "undefined") return fallback;
  const cs = getComputedStyle(document.documentElement);
  const rgb = (name: string, f: string) => {
    const v = cs.getPropertyValue(name).trim();
    return v ? `rgb(${v})` : f;
  };
  return {
    bg: rgb("--c-bg", fallback.bg),
    text: rgb("--c-textmid", fallback.text),
    grid: rgb("--c-bg3", fallback.grid),
    border: rgb("--c-border", fallback.border),
  };
}
