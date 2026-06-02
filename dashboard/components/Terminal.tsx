"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import GridLayout, { WidthProvider, type Layout } from "react-grid-layout";
import { useStream } from "./useStream";
import { StatusBar } from "./StatusBar";
import {
  WIDGETS, WIDGETS_BY_ID, WIDGET_CATEGORIES, WidgetFrame, type WidgetDef,
} from "./widgets";

const Grid = WidthProvider(GridLayout);
const STORE_KEY = "apex.terminal.v2";
const COLS = 12;
const ROW_H = 26;

type Instance = { key: string; widgetId: string };
type Space = { name: string; widgets: Instance[]; layout: Layout[] };
type Persisted = { active: number; spaces: Space[] };

function defaultSpaces(): Persisted {
  const main: Space = {
    name: "MAIN",
    widgets: [
      { key: "chart", widgetId: "chart" },
      { key: "watchlist", widgetId: "watchlist" },
      { key: "account", widgetId: "account" },
      { key: "positions", widgetId: "positions" },
      { key: "log", widgetId: "log" },
    ],
    layout: [
      { i: "chart", x: 0, y: 0, w: 7, h: 13, minW: 4, minH: 8 },
      { i: "watchlist", x: 7, y: 0, w: 5, h: 6, minW: 3, minH: 4 },
      { i: "account", x: 7, y: 6, w: 5, h: 7, minW: 3, minH: 5 },
      { i: "positions", x: 0, y: 13, w: 7, h: 7, minW: 4, minH: 4 },
      { i: "log", x: 7, y: 13, w: 5, h: 7, minW: 4, minH: 4 },
    ],
  };
  return { active: 0, spaces: [main] };
}

export function Terminal() {
  const { state, status } = useStream();
  const [data, setData] = useState<Persisted | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [query, setQuery] = useState("");
  const mounted = useRef(false);

  // Load persisted workspaces on mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      setData(raw ? (JSON.parse(raw) as Persisted) : defaultSpaces());
    } catch {
      setData(defaultSpaces());
    }
    mounted.current = true;
  }, []);

  const persist = useCallback((next: Persisted) => {
    setData(next);
    try { localStorage.setItem(STORE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
  }, []);

  const space = data?.spaces[data.active];

  const addWidget = useCallback((widgetId: string, at?: { x: number; y: number }) => {
    if (!data) return;
    const def = WIDGETS_BY_ID[widgetId];
    if (!def) return;
    const key = `${widgetId}-${Date.now().toString(36)}`;
    const sp = data.spaces[data.active];
    const item: Layout = {
      i: key, x: at?.x ?? 0, y: at?.y ?? Infinity, w: def.w, h: def.h, minW: def.minW, minH: def.minH,
    };
    const next = structuredClone(data);
    next.spaces[next.active].widgets.push({ key, widgetId });
    next.spaces[next.active].layout.push(item);
    persist(next);
  }, [data, persist]);

  const removeWidget = useCallback((key: string) => {
    if (!data) return;
    const next = structuredClone(data);
    const s = next.spaces[next.active];
    s.widgets = s.widgets.filter((w) => w.key !== key);
    s.layout = s.layout.filter((l) => l.i !== key);
    persist(next);
  }, [data, persist]);

  const onLayoutChange = useCallback((layout: Layout[]) => {
    if (!data || !mounted.current) return;
    const next = structuredClone(data);
    next.spaces[next.active].layout = layout;
    // persist without re-render churn
    try { localStorage.setItem(STORE_KEY, JSON.stringify(next)); } catch { /* ignore */ }
    setData(next);
  }, [data]);

  const addSpace = () => {
    if (!data) return;
    const next = structuredClone(data);
    next.spaces.push({ name: `WS ${next.spaces.length + 1}`, widgets: [], layout: [] });
    next.active = next.spaces.length - 1;
    persist(next);
  };
  const switchSpace = (i: number) => { if (data) persist({ ...data, active: i }); };
  const removeSpace = (i: number) => {
    if (!data || data.spaces.length <= 1) return;
    const next = structuredClone(data);
    next.spaces.splice(i, 1);
    next.active = Math.max(0, Math.min(next.active, next.spaces.length - 1));
    persist(next);
  };
  const resetSpace = () => { if (data && confirm("Reset this workspace layout?")) persist(defaultSpaces()); };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return WIDGET_CATEGORIES;
    return WIDGET_CATEGORIES.map((c) => ({
      name: c.name,
      items: c.items.filter((w) => `${w.name} ${w.code} ${w.category}`.toLowerCase().includes(q)),
    })).filter((c) => c.items.length);
  }, [query]);

  if (!data || !space) {
    return <div className="flex h-64 items-center justify-center font-mono text-sm text-textmid">Loading workspace…</div>;
  }

  return (
    <div className="flex h-[calc(100vh-220px)] min-h-[560px] overflow-hidden rounded-md border border-border bg-bg">
      {/* ── Retractable sidebar ── */}
      {sidebarOpen ? (
        <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-bg2">
          <div className="flex items-center justify-between border-b border-border px-3 py-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-gold">Widgets</span>
            <button onClick={() => setSidebarOpen(false)} title="Hide" className="px-1 font-mono text-textdim hover:text-gold">‹</button>
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search widgets…"
            className="m-2 rounded border border-border bg-bg3 px-2 py-1.5 font-mono text-[11px] text-textmid outline-none focus:border-gold"
          />
          <div className="min-h-0 flex-1 overflow-y-auto pb-3">
            {filtered.map((cat) => (
              <div key={cat.name} className="mb-1">
                <div className="px-3 py-1 font-mono text-[9px] uppercase tracking-[0.2em] text-textdim">{cat.name}</div>
                {cat.items.map((w) => (
                  <button
                    key={w.id}
                    draggable
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", w.id)}
                    onClick={() => addWidget(w.id)}
                    title={`Add ${w.name}`}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left transition hover:bg-bg3"
                  >
                    <span className="rounded bg-gold/10 px-1 py-0.5 font-mono text-[9px] text-gold">{w.code}</span>
                    <span className="text-[12px] text-textmid">{w.name}</span>
                    <span className="ml-auto font-mono text-[10px] text-textdim">+</span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </aside>
      ) : (
        <button
          onClick={() => setSidebarOpen(true)}
          title="Show widgets"
          className="flex w-6 shrink-0 items-center justify-center border-r border-border bg-bg2 transition hover:bg-bg3"
        >
          <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-gold" style={{ writingMode: "vertical-rl" }}>
            › Widgets
          </span>
        </button>
      )}

      {/* ── Workspace ── */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* command + status */}
        <div className="flex items-center gap-3 border-b border-border bg-bg2 px-3 py-1.5">
          <span className="font-mono text-[11px] font-bold tracking-[0.2em] text-gold">APEX</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { const m = WIDGETS.find((w) => `${w.name} ${w.code}`.toLowerCase().includes(query.trim().toLowerCase())); if (m) { addWidget(m.id); setQuery(""); } } }}
            placeholder="Command / search widgets — type & Enter"
            className="flex-1 rounded border border-border bg-bg3 px-3 py-1 font-mono text-[11px] text-textmid outline-none focus:border-gold"
          />
          {state && <span className="hidden font-mono text-[10px] text-textdim sm:inline">{status}</span>}
        </div>

        {state && <div className="px-3 pt-2"><StatusBar state={state} status={status} /></div>}

        {/* grid */}
        <div className="min-h-0 flex-1 overflow-auto p-2">
          {!state ? (
            <div className="mx-auto mt-10 max-w-md rounded-md border border-border bg-bg2 p-6 text-center">
              <div className="mb-2 font-mono text-sm text-gold">Waiting for your trading engine…</div>
              <p className="text-sm text-textmid">Start it on your machine (double-click <span className="text-gold">start.bat</span>) and live data fills the widgets within ~30s.</p>
            </div>
          ) : (
            <Grid
              className="layout"
              layout={space.layout}
              cols={COLS}
              rowHeight={ROW_H}
              margin={[8, 8]}
              draggableHandle=".widget-drag"
              isResizable
              isDraggable
              compactType="vertical"
              onLayoutChange={onLayoutChange}
              isDroppable
              droppingItem={{ i: "__drop__", w: 5, h: 7 }}
              onDrop={(_l: Layout[], item: any, e: any) => {
                const id = e?.dataTransfer?.getData("text/plain");
                if (id) addWidget(id, { x: item?.x ?? 0, y: item?.y ?? 0 });
              }}
            >
              {space.widgets.map((inst) => {
                const def: WidgetDef | undefined = WIDGETS_BY_ID[inst.widgetId];
                if (!def) return <div key={inst.key} />;
                return (
                  <div key={inst.key}>
                    <WidgetFrame code={def.code} title={def.name} onClose={() => removeWidget(inst.key)}>
                      {def.render(state)}
                    </WidgetFrame>
                  </div>
                );
              })}
            </Grid>
          )}
        </div>

        {/* workspace tabs */}
        <div className="flex items-center gap-1 border-t border-border bg-bg2 px-2 py-1">
          {data.spaces.map((sp, i) => (
            <span key={i} className={`group flex items-center rounded ${i === data.active ? "bg-gold/15" : "hover:bg-bg3"}`}>
              <button onClick={() => switchSpace(i)} className={`px-3 py-1 font-mono text-[10px] uppercase tracking-wider ${i === data.active ? "text-gold" : "text-textdim"}`}>
                {sp.name}
              </button>
              {data.spaces.length > 1 && (
                <button onClick={() => removeSpace(i)} className="px-1 font-mono text-[10px] text-textdim opacity-0 transition group-hover:opacity-100 hover:text-down">×</button>
              )}
            </span>
          ))}
          <button onClick={addSpace} title="New workspace" className="px-2 py-1 font-mono text-[11px] text-textdim hover:text-gold">+</button>
          <button onClick={resetSpace} title="Reset layout" className="ml-auto px-2 py-1 font-mono text-[10px] uppercase tracking-wider text-textdim hover:text-gold">Reset</button>
        </div>
      </div>
    </div>
  );
}
