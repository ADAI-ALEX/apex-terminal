"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import ReactFlow, {
  Background, BackgroundVariant, Controls, MiniMap,
  applyNodeChanges, type Node, type NodeChange,
} from "reactflow";
import { useStream } from "./useStream";
import { WidgetNode } from "./WidgetNode";
import { TerminalContext } from "./TerminalContext";
import { WIDGETS, WIDGETS_BY_ID, WIDGET_CATEGORIES, WidgetFrame } from "./widgets";
import { BacktestTab } from "./BacktestTab";
import { SignOutButton } from "./SignOutButton";
import { ThemeToggle } from "./ThemeToggle";

const STORE_KEY = "apex.terminal.v3";
type WNode = Node<{ widgetId: string }>;
type DockState = { left?: string; right?: string; leftW: number; rightW: number };
type Space = { name: string; nodes: WNode[]; dock?: DockState };
type Persisted = { active: number; spaces: Space[] };
const DEFAULT_DOCK: DockState = { leftW: 42, rightW: 42 };

const nodeTypes = { widget: WidgetNode };

function mk(widgetId: string, x: number, y: number, w: number, h: number): WNode {
  return {
    id: `${widgetId}-${Math.random().toString(36).slice(2, 7)}`,
    type: "widget",
    position: { x, y },
    data: { widgetId },
    style: { width: w, height: h },
    dragHandle: ".widget-drag",
  };
}

function defaultSpaces(): Persisted {
  return {
    active: 0,
    spaces: [{
      name: "MAIN",
      nodes: [
        mk("chart", 0, 0, 760, 460),
        mk("watchlist", 780, 0, 430, 220),
        mk("account", 780, 240, 430, 320),
        mk("positions", 0, 480, 760, 250),
        mk("log", 780, 580, 430, 250),
      ],
    }],
  };
}

export function Terminal() {
  const { state, status } = useStream();
  const [view, setView] = useState<"terminal" | "backtest">("terminal");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [query, setQuery] = useState("");

  const [nodes, setNodes] = useState<WNode[]>([]);
  const [active, setActive] = useState(0);
  const [spaceNames, setSpaceNames] = useState<string[]>(["MAIN"]);
  const [dock, setDock] = useState<DockState>(DEFAULT_DOCK);
  const [snapZone, setSnapZone] = useState<"left" | "right" | null>(null);

  const store = useRef<Persisted | null>(null);
  const activeRef = useRef(0);
  const loaded = useRef(false);
  const rfRef = useRef<any>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const nodesRef = useRef<WNode[]>([]);
  nodesRef.current = nodes;
  const zoneRef = useRef<{ candidate: "left" | "right" | null; timer: ReturnType<typeof setTimeout> | null }>({ candidate: null, timer: null });
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [maximizedId, setMaximizedId] = useState<string | null>(null);
  const [interacting, setInteracting] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [renaming, setRenaming] = useState<{ i: number; value: string } | null>(null);
  const [light, setLight] = useState(false);

  // Track the active theme so the canvas grid recolours with Dark/Light.
  useEffect(() => {
    const read = () => setLight(typeof document !== "undefined" && document.documentElement.classList.contains("theme-light"));
    read();
    window.addEventListener("apex-theme", read);
    return () => window.removeEventListener("apex-theme", read);
  }, []);
  const grid = light ? { lines: "#d6d6ce", dots: "#c2c2b8" } : { lines: "#1a1a1a", dots: "#242424" };

  // load
  useEffect(() => {
    let p: Persisted;
    try { p = JSON.parse(localStorage.getItem(STORE_KEY) || "") as Persisted; if (!p?.spaces?.length) throw 0; }
    catch { p = defaultSpaces(); }
    store.current = p;
    activeRef.current = p.active;
    setActive(p.active);
    setSpaceNames(p.spaces.map((s) => s.name));
    setNodes(p.spaces[p.active].nodes);
    setDock(p.spaces[p.active].dock ?? DEFAULT_DOCK);
    loaded.current = true;
  }, []);

  const saveStore = () => { try { localStorage.setItem(STORE_KEY, JSON.stringify(store.current)); } catch { /* ignore */ } };

  // persist nodes + dock → active space
  useEffect(() => {
    if (!loaded.current || !store.current) return;
    store.current.spaces[activeRef.current].nodes = nodes;
    store.current.spaces[activeRef.current].dock = dock;
    store.current.active = activeRef.current;
    saveStore();
  }, [nodes, dock]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((nds) => applyNodeChanges(changes, nds) as WNode[]);
  }, []);

  const addWidget = useCallback((widgetId: string) => {
    const def = WIDGETS_BY_ID[widgetId];
    if (!def) return;
    if (view !== "terminal") setView("terminal");
    setNodes((nds) => {
      const off = (nds.length % 6) * 28;
      return [...nds, mk(widgetId, 60 + off, 60 + off, def.w * 60, def.h * 24)];
    });
  }, [view]);

  const removeWidget = useCallback((id: string) => {
    setNodes((nds) => nds.filter((n) => n.id !== id));
  }, []);

  const deselectAll = useCallback(() => {
    setNodes((nds) => (nds.some((n) => n.selected) ? nds.map((n) => ({ ...n, selected: false })) : nds));
  }, []);

  // Maximize = overlay that fills the canvas region (the actual node is untouched, so
  // the user's pan/zoom is preserved and restoring returns it to its exact place).
  const toggleMaximize = useCallback((id: string) => {
    setMaximizedId((cur) => (cur === id ? null : id));
  }, []);

  const addWidgetAt = useCallback((widgetId: string, pos: { x: number; y: number }) => {
    const def = WIDGETS_BY_ID[widgetId];
    if (!def) return;
    setNodes((nds) => [...nds, mk(widgetId, pos.x, pos.y, def.w * 60, def.h * 24)]);
  }, []);

  // ── Docking (Windows-style edge snap) ──────────────────────────────
  const dockNode = useCallback((id: string, side: "left" | "right") => {
    const n = nodesRef.current.find((x) => x.id === id);
    if (!n) return;
    setDock((d) => ({ ...d, [side]: n.data.widgetId }));
    setNodes((nds) => nds.filter((x) => x.id !== id));
  }, []);

  const undock = useCallback((side: "left" | "right") => {
    setDock((d) => {
      const widgetId = d[side];
      if (widgetId) addWidget(widgetId);
      return { ...d, [side]: undefined };
    });
  }, [addWidget]);

  // While dragging a node, detect proximity to the left/right edge; after a short
  // hold show the snap preview. Release in the zone → dock that side.
  const onNodeDrag = useCallback((e: React.MouseEvent) => {
    const rect = mainRef.current?.getBoundingClientRect();
    if (!rect) return;
    const EDGE = 60;
    const x = (e as any).clientX ?? 0;
    let z: "left" | "right" | null = null;
    if (x <= rect.left + EDGE) z = "left";
    else if (x >= rect.right - EDGE) z = "right";
    if (z !== zoneRef.current.candidate) {
      zoneRef.current.candidate = z;
      if (zoneRef.current.timer) { clearTimeout(zoneRef.current.timer); zoneRef.current.timer = null; }
      setSnapZone(null);
      if (z) zoneRef.current.timer = setTimeout(() => setSnapZone(z), 450);
    }
  }, []);

  const onNodeDragStop = useCallback((_e: React.MouseEvent, node: Node) => {
    clearHide(); setInteracting(false);
    if (zoneRef.current.timer) { clearTimeout(zoneRef.current.timer); zoneRef.current.timer = null; }
    setSnapZone((z) => { if (z) dockNode(node.id, z); return null; });
    zoneRef.current.candidate = null;
  }, [dockNode]);

  const startDockResize = (side: "left" | "right") => (e: React.MouseEvent) => {
    e.preventDefault();
    const rect = mainRef.current?.getBoundingClientRect();
    if (!rect) return;
    const onMove = (ev: MouseEvent) => {
      const pct = side === "left"
        ? ((ev.clientX - rect.left) / rect.width) * 100
        : ((rect.right - ev.clientX) / rect.width) * 100;
      setDock((d) => ({ ...d, [side === "left" ? "leftW" : "rightW"]: Math.min(82, Math.max(18, pct)) }));
    };
    const onUp = () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const dockPanel = (side: "left" | "right") => {
    const widgetId = dock[side];
    if (!widgetId) return null;
    const def = WIDGETS_BY_ID[widgetId];
    if (!def) return null;
    const w = side === "left" ? dock.leftW : dock.rightW;
    return (
      <div className={`absolute top-0 bottom-0 z-20 p-1.5 ${side === "left" ? "left-0" : "right-0"}`} style={{ width: `${w}%` }}>
        <div className="apex-window h-full w-full">
          <WidgetFrame code={def.code} title={`${def.name} · docked`} onClose={() => undock(side)}>
            {state ? def.render(state) : <div className="flex h-full items-center justify-center font-mono text-[11px] text-textdim">waiting for engine…</div>}
          </WidgetFrame>
        </div>
        <div
          onMouseDown={startDockResize(side)}
          title="Drag to resize"
          className={`absolute top-0 bottom-0 w-1.5 cursor-col-resize bg-transparent transition hover:bg-gold/50 ${side === "left" ? "right-0" : "left-0"}`}
        />
      </div>
    );
  };

  // MiniMap visibility: pan (drag) hides instantly on release; zoom (wheel) lingers 0.25s.
  const clearHide = () => { if (hideTimer.current) { clearTimeout(hideTimer.current); hideTimer.current = null; } };
  const startInteract = useCallback(() => { clearHide(); setInteracting(true); }, []);
  const endInteract = useCallback((e?: any) => {
    clearHide();
    const t: string = (e && e.type) || "";
    if (t.startsWith("mouse") || t.startsWith("pointer") || t.startsWith("touch")) {
      setInteracting(false); // pan released → gone immediately
    } else {
      hideTimer.current = setTimeout(() => setInteracting(false), 150); // zoom → brief linger
    }
  }, []);

  const onDropWidget = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const id = e.dataTransfer.getData("application/apex-widget");
    if (!id) return;
    const inst = rfRef.current;
    const pos = inst?.screenToFlowPosition
      ? inst.screenToFlowPosition({ x: e.clientX, y: e.clientY })
      : { x: 80, y: 80 };
    if (view !== "terminal") setView("terminal");
    addWidgetAt(id, pos);
  }, [addWidgetAt, view]);

  const toggleFullscreen = () => {
    if (typeof document === "undefined") return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void rootRef.current?.requestFullscreen?.();
  };

  const commitRename = () => {
    if (!renaming || !store.current) return setRenaming(null);
    const name = renaming.value.trim();
    if (name) {
      store.current.spaces[renaming.i].name = name;
      setSpaceNames(store.current.spaces.map((s) => s.name));
      try { localStorage.setItem(STORE_KEY, JSON.stringify(store.current)); } catch { /* ignore */ }
    }
    setRenaming(null);
  };

  const saveCurrent = () => {
    if (!store.current) return;
    store.current.spaces[activeRef.current].nodes = nodes;
    store.current.spaces[activeRef.current].dock = dock;
  };
  const switchSpace = (i: number) => {
    if (!store.current) return;
    saveCurrent();
    activeRef.current = i;
    setActive(i);
    setNodes(store.current.spaces[i].nodes);
    setDock(store.current.spaces[i].dock ?? DEFAULT_DOCK);
  };
  const addSpace = () => {
    if (!store.current) return;
    saveCurrent();
    store.current.spaces.push({ name: `WS ${store.current.spaces.length + 1}`, nodes: [], dock: { ...DEFAULT_DOCK } });
    const i = store.current.spaces.length - 1;
    activeRef.current = i; setActive(i);
    setSpaceNames(store.current.spaces.map((s) => s.name));
    setNodes([]); setDock({ ...DEFAULT_DOCK });
  };
  const removeSpace = (i: number) => {
    if (!store.current || store.current.spaces.length <= 1) return;
    store.current.spaces.splice(i, 1);
    const ni = Math.max(0, Math.min(activeRef.current, store.current.spaces.length - 1));
    activeRef.current = ni; setActive(ni);
    setSpaceNames(store.current.spaces.map((s) => s.name));
    setNodes(store.current.spaces[ni].nodes);
    setDock(store.current.spaces[ni].dock ?? DEFAULT_DOCK);
    saveStore();
  };
  const clearSpace = () => { if (confirm("Clear all widgets in this workspace?")) { setNodes([]); setDock({ ...DEFAULT_DOCK }); } };
  const resetAll = () => {
    if (!confirm("Reset all workspaces to default?")) return;
    const p = defaultSpaces();
    store.current = p; activeRef.current = 0; setActive(0);
    setSpaceNames(p.spaces.map((s) => s.name)); setNodes(p.spaces[0].nodes); setDock({ ...DEFAULT_DOCK });
    try { localStorage.setItem(STORE_KEY, JSON.stringify(p)); } catch { /* ignore */ }
  };

  const catalog = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return WIDGET_CATEGORIES;
    return WIDGET_CATEGORIES.map((c) => ({ name: c.name, items: c.items.filter((w) => `${w.name} ${w.code}`.toLowerCase().includes(q)) })).filter((c) => c.items.length);
  }, [query]);

  return (
    <TerminalContext.Provider value={{ state, removeWidget, toggleMaximize, deselectAll, maximizedId }}>
      <div ref={rootRef} className="flex h-screen w-screen flex-col overflow-hidden bg-bg text-textmid">
        {/* ── Top bar ── */}
        <header className="flex items-center gap-3 border-b border-border bg-bg2 px-3 py-1.5">
          <span className="font-mono text-sm font-bold tracking-[0.25em] text-gold">APEX</span>
          <div className="flex overflow-hidden rounded border border-border font-mono text-[10px]">
            <button onClick={() => setView("terminal")} className={`px-3 py-1 uppercase tracking-wider ${view === "terminal" ? "bg-gold/15 text-gold" : "text-textdim hover:text-textmid"}`}>Terminal</button>
            <button onClick={() => setView("backtest")} className={`border-l border-border px-3 py-1 uppercase tracking-wider ${view === "backtest" ? "bg-gold/15 text-gold" : "text-textdim hover:text-textmid"}`}>Backtest</button>
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { const m = WIDGETS.find((w) => `${w.name} ${w.code}`.toLowerCase().includes(query.trim().toLowerCase())); if (m) { addWidget(m.id); setQuery(""); } } }}
            placeholder="COMMAND OR SEARCH WIDGETS · ENTER"
            className="flex-1 rounded border border-border bg-bg3 px-3 py-1 font-mono text-[11px] uppercase tracking-wider text-textmid outline-none placeholder:text-textdim focus:border-gold"
          />
          <StatusDot status={status} mode={state?.mode} />
          <Clock />
          <ThemeToggle />
          <button onClick={toggleFullscreen} title="Fullscreen terminal" className="rounded border border-border px-2 py-1 font-mono text-[12px] text-textmid transition hover:border-gold hover:text-gold">⛶</button>
        </header>

        {/* ── Body ── */}
        <div className="flex min-h-0 flex-1">
          {/* Sidebar */}
          {sidebarOpen ? (
            <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-bg2">
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-gold">Widgets</span>
                <button onClick={() => setSidebarOpen(false)} title="Hide sidebar" className="px-1 font-mono text-textdim hover:text-gold">‹</button>
              </div>
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="search…" className="m-2 rounded border border-border bg-bg3 px-2 py-1.5 font-mono text-[11px] text-textmid outline-none focus:border-gold" />
              <div className="min-h-0 flex-1 overflow-y-auto pb-2">
                {catalog.map((cat) => (
                  <div key={cat.name} className="mb-1">
                    <div className="px-3 py-1 font-mono text-[9px] uppercase tracking-[0.2em] text-textdim">{cat.name}</div>
                    {cat.items.map((w) => (
                      <button
                        key={w.id}
                        draggable
                        onDragStart={(e) => { e.dataTransfer.setData("application/apex-widget", w.id); e.dataTransfer.effectAllowed = "copy"; }}
                        onClick={() => addWidget(w.id)}
                        title={`Drag onto the canvas, or click to add ${w.name}`}
                        className="group/item flex w-full cursor-grab items-center gap-2 px-3 py-1.5 text-left transition hover:bg-bg3 active:cursor-grabbing"
                      >
                        <span className="rounded bg-gold/10 px-1 py-0.5 font-mono text-[9px] text-gold">{w.code}</span>
                        <span className="text-[12px] text-textmid">{w.name}</span>
                        <span className="ml-auto font-mono text-[11px] text-textdim opacity-0 transition group-hover/item:opacity-100">⠿</span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
              {/* bottom: settings + sign out */}
              <div className="border-t border-border p-2">
                <Link href="/settings" className="mb-2 flex items-center gap-2 rounded px-2 py-1.5 text-[12px] text-textmid transition hover:bg-bg3 hover:text-gold">
                  <span className="rounded bg-gold/10 px-1 py-0.5 font-mono text-[9px] text-gold">SET</span> Settings
                </Link>
                <SignOutButton />
              </div>
            </aside>
          ) : (
            <button onClick={() => setSidebarOpen(true)} title="Show widgets" className="flex w-6 shrink-0 items-center justify-center border-r border-border bg-bg2 transition hover:bg-bg3">
              <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-gold" style={{ writingMode: "vertical-rl" }}>› Widgets</span>
            </button>
          )}

          {/* Canvas / Backtest */}
          <main
            ref={mainRef}
            className="relative min-h-0 flex-1"
            onDragOver={(e) => { if (e.dataTransfer.types.includes("application/apex-widget")) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setDragOver(true); } }}
            onDragLeave={(e) => { if (e.currentTarget === e.target) setDragOver(false); }}
            onDrop={onDropWidget}
          >
            {view === "terminal" ? (
              <ReactFlow
                nodes={nodes}
                edges={[]}
                onNodesChange={onNodesChange}
                onInit={(inst) => { rfRef.current = inst; }}
                onMoveStart={startInteract}
                onMoveEnd={(e) => endInteract(e)}
                onNodeDragStart={startInteract}
                onNodeDrag={(e) => onNodeDrag(e)}
                onNodeDragStop={onNodeDragStop}
                onPaneClick={deselectAll}
                nodeTypes={nodeTypes}
                proOptions={{ hideAttribution: true }}
                minZoom={0.25}
                maxZoom={2}
                fitView
                panOnDrag
                zoomOnScroll
                selectionOnDrag={false}
                deleteKeyCode={null}
              >
                <Background id="lines" variant={BackgroundVariant.Lines} gap={66} size={1} color={grid.lines} />
                <Background id="dots" variant={BackgroundVariant.Dots} gap={22} size={1} color={grid.dots} />
                <Controls showInteractive={false} />
                {interacting && (
                  <MiniMap pannable zoomable nodeColor="#c9a84c66" nodeStrokeColor="#c9a84c" maskColor={light ? "rgba(0,0,0,0.15)" : "rgba(0,0,0,0.6)"} />
                )}
              </ReactFlow>
            ) : (
              <div className="absolute inset-0 overflow-auto p-4">
                <BacktestTab />
              </div>
            )}

            {/* Docked panels (fixed to the edges, stay put while the canvas pans) */}
            {view === "terminal" && dockPanel("left")}
            {view === "terminal" && dockPanel("right")}

            {/* Snap preview while dragging a widget toward an edge */}
            {view === "terminal" && snapZone && (
              <div
                className="pointer-events-none absolute top-0 bottom-0 z-40 rounded-lg border-2 border-dashed border-gold/70 bg-gold/10"
                style={{ [snapZone]: 0, width: `${snapZone === "left" ? dock.leftW : dock.rightW}%` } as React.CSSProperties}
              />
            )}

            {/* Drag-over highlight when dropping a widget from the sidebar */}
            {dragOver && view === "terminal" && (
              <div className="pointer-events-none absolute inset-2 z-10 rounded-lg border-2 border-dashed border-gold/60 bg-gold/5" />
            )}

            {/* Maximize overlay: fills the canvas region, leaves pan/zoom untouched */}
            {view === "terminal" && maximizedId && (() => {
              const inst = nodes.find((n) => n.id === maximizedId);
              const def = inst && WIDGETS_BY_ID[inst.data.widgetId];
              if (!def) return null;
              return (
                <div className="absolute inset-0 z-30 bg-bg p-2">
                  <div className="apex-window h-full w-full">
                    <WidgetFrame
                      code={def.code} title={def.name} maximized
                      onMaximize={() => setMaximizedId(null)}
                      onClose={() => { removeWidget(maximizedId); setMaximizedId(null); }}
                    >
                      {state ? def.render(state) : <div className="flex h-full items-center justify-center font-mono text-[11px] text-textdim">waiting for engine…</div>}
                    </WidgetFrame>
                  </div>
                </div>
              );
            })()}
          </main>
        </div>

        {/* ── Bottom bar ── */}
        <footer className="flex items-center gap-1 border-t border-border bg-bg2 px-2 py-1">
          {spaceNames.map((name, i) => (
            <span key={i} className={`group flex items-center rounded ${i === active ? "bg-gold/15" : "hover:bg-bg3"}`}>
              {renaming?.i === i ? (
                <input
                  autoFocus
                  value={renaming.value}
                  onChange={(e) => setRenaming({ i, value: e.target.value })}
                  onBlur={commitRename}
                  onKeyDown={(e) => { if (e.key === "Enter") commitRename(); if (e.key === "Escape") setRenaming(null); }}
                  className="w-24 rounded bg-bg3 px-2 py-1 font-mono text-[10px] uppercase text-gold outline-none"
                />
              ) : (
                <button
                  onClick={() => switchSpace(i)}
                  onDoubleClick={() => setRenaming({ i, value: name })}
                  title="Double-click to rename"
                  className={`px-3 py-1 font-mono text-[10px] uppercase tracking-wider ${i === active ? "text-gold" : "text-textdim"}`}
                >
                  {name}
                </button>
              )}
              {spaceNames.length > 1 && <button onClick={() => removeSpace(i)} className="px-1 font-mono text-[10px] text-textdim opacity-0 transition group-hover:opacity-100 hover:text-down">×</button>}
            </span>
          ))}
          <button onClick={addSpace} title="New workspace" className="px-2 py-1 font-mono text-[12px] text-textdim hover:text-gold">+</button>
          <span className="ml-auto flex items-center gap-3 font-mono text-[10px] uppercase tracking-wider text-textdim">
            <button onClick={clearSpace} className="hover:text-gold">Clear</button>
            <button onClick={resetAll} className="hover:text-gold">Reset</button>
            <span className="text-textdim/60">v1.2</span>
          </span>
        </footer>
      </div>
    </TerminalContext.Provider>
  );
}

function Clock() {
  const [now, setNow] = useState<string>("");
  useEffect(() => {
    const tick = () => setNow(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return <span className="font-mono text-[12px] tabular-nums text-gold">{now}</span>;
}

function StatusDot({ status, mode }: { status: string; mode?: string }) {
  const live = status === "live";
  return (
    <span className="hidden items-center gap-1.5 font-mono text-[10px] text-textdim sm:flex">
      <span className={`h-1.5 w-1.5 rounded-full ${live ? "bg-up" : "bg-down"}`} />
      {mode ?? "—"}
    </span>
  );
}
