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
type Side = "left" | "right" | "top" | "bottom";
// Docked widget per side + each side's size (% of width for L/R, % of height for T/B).
type DockState = {
  left?: string; right?: string; top?: string; bottom?: string;
  leftW: number; rightW: number; topH: number; bottomH: number;
};
type Space = { name: string; nodes: WNode[]; dock?: DockState };
type Persisted = { active: number; spaces: Space[] };
const DEFAULT_DOCK: DockState = { leftW: 30, rightW: 30, topH: 32, bottomH: 32 };
// Older persisted spaces may lack top/bottom keys — backfill so `${dock.topH}%` is valid.
const mergeDock = (d?: Partial<DockState>): DockState => ({ ...DEFAULT_DOCK, ...(d || {}) });

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
  // Persist the active top tab (restored on reload); set in an effect to avoid a
  // hydration mismatch.
  const [view, setView] = useState<"terminal" | "backtest">("terminal");
  useEffect(() => {
    const saved = localStorage.getItem("apex.view");
    if (saved === "terminal" || saved === "backtest") setView(saved);
  }, []);
  useEffect(() => { try { localStorage.setItem("apex.view", view); } catch { /* ignore */ } }, [view]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [query, setQuery] = useState("");

  const [nodes, setNodes] = useState<WNode[]>([]);
  const [active, setActive] = useState(0);
  const [spaceNames, setSpaceNames] = useState<string[]>(["MAIN"]);
  const [dock, setDock] = useState<DockState>(DEFAULT_DOCK);
  const [snapZone, setSnapZone] = useState<Side | null>(null);

  const store = useRef<Persisted | null>(null);
  const activeRef = useRef(0);
  const loaded = useRef(false);
  const rfRef = useRef<any>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const nodesRef = useRef<WNode[]>([]);
  nodesRef.current = nodes;
  const dockedNodeRef = useRef<{ left?: WNode; right?: WNode; top?: WNode; bottom?: WNode }>({});
  const dragTimer = useRef<ReturnType<typeof setTimeout> | null>(null);   // 1s edge-hold → auto-pan
  const dragEdgeRef = useRef<Side | null | undefined>(undefined);          // current edge under cursor
  const panRAF = useRef(0);                                                // manual auto-pan rAF handle
  const draggedIdRef = useRef<string | null>(null);                        // node being dragged
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [maximizedId, setMaximizedId] = useState<string | null>(null);
  const [interacting, setInteracting] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [renaming, setRenaming] = useState<{ i: number; value: string } | null>(null);
  const [confirmDlg, setConfirmDlg] = useState<null | { title: string; message: string; confirmLabel: string; onConfirm: () => void }>(null);
  const [light, setLight] = useState(false);
  const [isPhone, setIsPhone] = useState(false);   // small touch device (short side ≤ 500px)
  const [isSmall, setIsSmall] = useState(false);    // narrow viewport → overlay sidebar
  const [portrait, setPortrait] = useState(false);
  const autoSidebar = useRef(true);                 // only auto-collapse the sidebar once

  // Responsive: track viewport size/orientation so the terminal fits phones & tablets.
  useEffect(() => {
    const check = () => {
      const w = window.innerWidth, h = window.innerHeight;
      setIsPhone(Math.min(w, h) <= 500);
      setPortrait(h > w);
      const small = w < 768;
      setIsSmall(small);
      if (small && autoSidebar.current) { setSidebarOpen(false); autoSidebar.current = false; }
    };
    check();
    window.addEventListener("resize", check);
    window.addEventListener("orientationchange", check);
    return () => { window.removeEventListener("resize", check); window.removeEventListener("orientationchange", check); };
  }, []);

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
    setDock(mergeDock(p.spaces[p.active].dock));
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
    // Add the widget at its natural footprint and then frame it: pan to the new window
    // and lift the zoom into a readable band (0.8–1.1). This is what fixes "too small
    // when I put it in" — opening a widget while zoomed right out now scales it sensibly
    // instead of dropping a tiny box into a far-zoomed canvas.
    const w = def.w * 60, h = def.h * 24;
    const z = rfRef.current?.getZoom?.() ?? 1;
    const targetZoom = Math.min(1.1, Math.max(0.8, z));
    const rect = mainRef.current?.getBoundingClientRect();
    let center: { x: number; y: number } | null = null;
    if (rect && rfRef.current?.screenToFlowPosition) {
      center = rfRef.current.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 });
    }
    const pos = center ? { x: center.x - w / 2, y: center.y - h / 2 } : { x: 80, y: 80 };
    setNodes((nds) => [...nds, mk(widgetId, pos.x, pos.y, w, h)]);
    if (center) rfRef.current?.setCenter?.(center.x, center.y, { zoom: targetZoom, duration: 350 });
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
    const z = rfRef.current?.getZoom?.() ?? 1; // keep on-screen size consistent at any zoom
    const w = (def.w * 60) / z, h = (def.h * 24) / z;
    setNodes((nds) => [...nds, mk(widgetId, pos.x - w / 2, pos.y - h / 2, w, h)]);
  }, []);

  // ── Docking (edge snap, all four sides) ─────────────────────────────
  // Geometry for a docked panel / its snap preview. Left & right run the FULL height
  // and sit at the walls; top & bottom sit BETWEEN whatever side panels exist (and only
  // reach the walls when no side panel is docked) — the layout from the user's sketch.
  const dockGeom = useCallback((side: Side): React.CSSProperties => {
    const lx = dock.left ? `${dock.leftW}%` : "0";
    const rx = dock.right ? `${dock.rightW}%` : "0";
    if (side === "left") return { left: 0, top: 0, bottom: 0, width: `${dock.leftW}%` };
    if (side === "right") return { right: 0, top: 0, bottom: 0, width: `${dock.rightW}%` };
    if (side === "top") return { top: 0, left: lx, right: rx, height: `${dock.topH}%` };
    return { bottom: 0, left: lx, right: rx, height: `${dock.bottomH}%` };
  }, [dock]);

  const dockNode = useCallback((id: string, side: Side) => {
    const n = nodesRef.current.find((x) => x.id === id);
    if (!n) return;
    dockedNodeRef.current[side] = n; // remember exact node so close() restores it
    setDock((d) => ({ ...d, [side]: n.data.widgetId }));
    setNodes((nds) => nds.filter((x) => x.id !== id));
  }, []);

  // Undock: close() restores the widget to its ORIGINAL spot; a drag passes `at` to
  // drop it where released.
  const undock = useCallback((side: Side, at?: { x: number; y: number }) => {
    const orig = dockedNodeRef.current[side];
    dockedNodeRef.current[side] = undefined;
    const sizeKey = ({ left: "leftW", right: "rightW", top: "topH", bottom: "bottomH" } as const)[side];
    // Reset this side's size so the NEXT tab docked here starts at the default size,
    // not whatever the previous (now-removed) tab had been resized to.
    setDock((d) => ({ ...d, [side]: undefined, [sizeKey]: DEFAULT_DOCK[sizeKey] }));
    if (orig) setNodes((nds) => [...nds, at ? { ...orig, position: at } : orig]);
  }, []);

  const clearDragTimer = () => { if (dragTimer.current) { clearTimeout(dragTimer.current); dragTimer.current = null; } };

  // Manual auto-pan (React Flow's built-in can't be re-gated mid-drag once started — it
  // would keep panning after you leave the edge and skip the 1s lock the next time). We
  // scroll the viewport ourselves and shift the dragged node by the inverse so it stays
  // under the cursor. Fully start/stop-able, so every edge contact gets a fresh 1s hold.
  const stopAutoPan = useCallback(() => {
    if (panRAF.current) { cancelAnimationFrame(panRAF.current); panRAF.current = 0; }
  }, []);
  const startAutoPan = useCallback((edge: Side) => {
    stopAutoPan();
    const STEP = 14;
    const tick = () => {
      const vp = rfRef.current?.getViewport?.();
      if (vp) {
        const dx = edge === "left" ? STEP : edge === "right" ? -STEP : 0;
        const dy = edge === "top" ? STEP : edge === "bottom" ? -STEP : 0;
        rfRef.current.setViewport({ x: vp.x + dx, y: vp.y + dy, zoom: vp.zoom });
        const id = draggedIdRef.current;
        if (id) setNodes((nds) => nds.map((n) => (n.id === id
          ? { ...n, position: { x: n.position.x - dx / vp.zoom, y: n.position.y - dy / vp.zoom } }
          : n)));
      }
      panRAF.current = requestAnimationFrame(tick);
    };
    panRAF.current = requestAnimationFrame(tick);
  }, [stopAutoPan]);

  // While dragging a node toward an edge: show the dock outline and hold the map still.
  // If still held at the same edge after 1s, drop the outline and start auto-panning
  // ("auto workspace move"). Releasing while the outline is up docks to that side.
  const onNodeDrag = useCallback((e: React.MouseEvent) => {
    const rect = mainRef.current?.getBoundingClientRect();
    if (!rect) return;
    const EDGE = 56;
    const x = (e as { clientX?: number }).clientX ?? 0;
    const y = (e as { clientY?: number }).clientY ?? 0;
    const z: Side | null =
      x <= rect.left + EDGE ? "left"
      : x >= rect.right - EDGE ? "right"
      : y <= rect.top + EDGE ? "top"
      : y >= rect.bottom - EDGE ? "bottom"
      : null;
    if (z === dragEdgeRef.current) return; // unchanged → keep current outline/pan
    dragEdgeRef.current = z;
    clearDragTimer();
    stopAutoPan();            // leaving an edge stops its pan immediately → fresh lock next time
    setSnapZone(z);
    if (z) dragTimer.current = setTimeout(() => { setSnapZone(null); startAutoPan(z); }, 1000);
  }, [startAutoPan, stopAutoPan]);

  const onNodeDragStop = useCallback((_e: React.MouseEvent, node: Node) => {
    clearHide(); setInteracting(false);
    clearDragTimer();
    stopAutoPan();
    dragEdgeRef.current = undefined;
    draggedIdRef.current = null;
    setSnapZone((z) => { if (z) dockNode(node.id, z); return null; });
  }, [dockNode, stopAutoPan]);

  // Resize a docked panel by dragging its inner edge — horizontal for L/R, vertical for T/B.
  const startDockResize = (side: Side) => (e: React.MouseEvent) => {
    e.preventDefault(); e.stopPropagation();
    const rect = mainRef.current?.getBoundingClientRect();
    if (!rect) return;
    const key = ({ left: "leftW", right: "rightW", top: "topH", bottom: "bottomH" } as const)[side];
    const onMove = (ev: MouseEvent) => {
      const pct =
        side === "left" ? ((ev.clientX - rect.left) / rect.width) * 100
        : side === "right" ? ((rect.right - ev.clientX) / rect.width) * 100
        : side === "top" ? ((ev.clientY - rect.top) / rect.height) * 100
        : ((rect.bottom - ev.clientY) / rect.height) * 100;
      setDock((d) => ({ ...d, [key]: Math.min(82, Math.max(12, pct)) }));
    };
    const onUp = () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const dockPanel = (side: Side) => {
    const widgetId = dock[side];
    if (!widgetId) return null;
    const def = WIDGETS_BY_ID[widgetId];
    if (!def) return null;
    const handleCls =
      side === "left" ? "top-0 bottom-0 right-0 w-1.5 cursor-col-resize"
      : side === "right" ? "top-0 bottom-0 left-0 w-1.5 cursor-col-resize"
      : side === "top" ? "left-0 right-0 bottom-0 h-1.5 cursor-row-resize"
      : "left-0 right-0 top-0 h-1.5 cursor-row-resize";
    return (
      <div
        key={side}
        className="absolute z-20"
        style={dockGeom(side)}
        // Drag the docked window out: drop in the canvas to float, or near an edge to re-dock.
        draggable
        onDragStart={(e) => { e.dataTransfer.setData("application/apex-dock", side); e.dataTransfer.effectAllowed = "move"; }}
        onDragEnd={() => setSnapZone(null)}
      >
        {/* Flush to the edge — no padding, square corners — so no workspace shows through. */}
        <div className="apex-window h-full w-full overflow-hidden" style={{ borderRadius: 0 }}>
          <WidgetFrame code={def.code} title={`${def.name} · docked`} onClose={() => undock(side)}>
            {state ? def.render(state) : <div className="flex h-full items-center justify-center font-mono text-[11px] text-textdim">waiting for engine…</div>}
          </WidgetFrame>
        </div>
        <div
          onMouseDown={startDockResize(side)}
          title="Drag to resize"
          className={`absolute ${handleCls} bg-transparent transition hover:bg-gold/50`}
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
    setSnapZone(null);
    const rect = mainRef.current?.getBoundingClientRect();
    const flowPos = rfRef.current?.screenToFlowPosition
      ? rfRef.current.screenToFlowPosition({ x: e.clientX, y: e.clientY })
      : { x: 80, y: 80 };

    // Re-positioning a docked window: near an edge → re-dock there, else float at drop.
    const fromSide = e.dataTransfer.getData("application/apex-dock") as Side | "";
    if (fromSide === "left" || fromSide === "right" || fromSide === "top" || fromSide === "bottom") {
      let toSide: Side | null = null;
      if (rect) {
        const rx = (e.clientX - rect.left) / rect.width, ry = (e.clientY - rect.top) / rect.height;
        toSide = rx <= 0.15 ? "left" : rx >= 0.85 ? "right" : ry <= 0.15 ? "top" : ry >= 0.85 ? "bottom" : null;
      }
      if (toSide && toSide !== fromSide) {
        const orig = dockedNodeRef.current[fromSide];
        dockedNodeRef.current[fromSide] = undefined;
        dockedNodeRef.current[toSide] = orig;
        const fromKey = ({ left: "leftW", right: "rightW", top: "topH", bottom: "bottomH" } as const)[fromSide];
        setDock((d) => ({ ...d, [fromSide]: undefined, [fromKey]: DEFAULT_DOCK[fromKey], [toSide!]: orig?.data.widgetId ?? d[fromSide] }));
      } else if (!toSide) {
        undock(fromSide, flowPos);
      }
      return;
    }

    const id = e.dataTransfer.getData("application/apex-widget");
    if (!id) return;
    if (view !== "terminal") setView("terminal");
    addWidgetAt(id, flowPos);
  }, [addWidgetAt, undock, view]);

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
    setView("terminal");   // workspaces live on the terminal canvas — show it
    saveCurrent();
    activeRef.current = i;
    setActive(i);
    setNodes(store.current.spaces[i].nodes);
    setDock(mergeDock(store.current.spaces[i].dock));
  };
  const addSpace = () => {
    if (!store.current) return;
    setView("terminal");
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
    setDock(mergeDock(store.current.spaces[ni].dock));
    saveStore();
  };
  const doClear = () => { setNodes([]); setDock({ ...DEFAULT_DOCK }); };
  // Reset ONLY the active workspace back to the default widget layout (fresh ids),
  // leaving every other workspace untouched. The persist effect saves it.
  const doReset = () => {
    setNodes(defaultSpaces().spaces[0].nodes);
    setDock({ ...DEFAULT_DOCK });
  };
  // In-app confirmation (matches the Sign-out dialog) instead of the browser confirm().
  const clearSpace = () => {
    setView("terminal");
    setConfirmDlg({
      title: "Clear workspace?",
      message: "This removes every widget and docked panel in the current workspace.",
      confirmLabel: "Clear",
      onConfirm: doClear,
    });
  };
  const resetAll = () => {
    setView("terminal");
    setConfirmDlg({
      title: "Reset workspace?",
      message: "This restores the current workspace to its default widget layout. Your other workspaces are unaffected.",
      confirmLabel: "Reset",
      onConfirm: doReset,
    });
  };

  const catalog = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return WIDGET_CATEGORIES;
    return WIDGET_CATEGORIES.map((c) => ({ name: c.name, items: c.items.filter((w) => `${w.name} ${w.code}`.toLowerCase().includes(q)) })).filter((c) => c.items.length);
  }, [query]);

  return (
    <TerminalContext.Provider value={{ state, removeWidget, toggleMaximize, deselectAll, maximizedId }}>
      <div
        ref={rootRef}
        data-apex-root
        // 100dvh (dynamic viewport height) so the terminal fits the *visible* area on
        // mobile — 100vh includes the address-bar space and caused the page to scroll.
        // h-screen stays as a fallback for browsers without dvh.
        style={{ height: "100dvh" }}
        className="relative flex h-screen w-screen flex-col overflow-hidden bg-bg text-textmid"
      >
        {/* Phones must be landscape — the terminal is too dense for portrait. */}
        {isPhone && portrait && (
          <div className="absolute inset-0 z-[100] flex flex-col items-center justify-center gap-4 bg-bg p-8 text-center">
            <div className="text-5xl">⟳</div>
            <div className="font-mono text-sm uppercase tracking-[0.3em] text-gold">Rotate your device</div>
            <p className="max-w-xs text-sm text-textdim">Apex Terminal runs in landscape. Turn your phone sideways to continue.</p>
          </div>
        )}
        {/* ── Top bar (compact on mobile — search hides, tighter padding) ── */}
        <header className="flex items-center gap-2 border-b border-border bg-bg2 px-2 py-1 sm:gap-3 sm:px-3 sm:py-1.5">
          <span className="font-mono text-sm font-bold tracking-[0.25em] text-gold">APEX</span>
          <div className="flex overflow-hidden rounded border border-border font-mono text-[10px]">
            <button onClick={() => setView("terminal")} className={`px-3 py-1 uppercase tracking-wider ${view === "terminal" ? "bg-gold/15 text-gold" : "text-textdim hover:text-textmid"}`}>Terminal</button>
            <button onClick={() => setView("backtest")} className={`border-l border-border px-3 py-1 uppercase tracking-wider ${view === "backtest" ? "bg-gold/15 text-gold" : "text-textdim hover:text-textmid"}`}>Algorithms</button>
          </div>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { const m = WIDGETS.find((w) => `${w.name} ${w.code}`.toLowerCase().includes(query.trim().toLowerCase())); if (m) { addWidget(m.id); setQuery(""); } } }}
            placeholder="COMMAND OR SEARCH WIDGETS · ENTER"
            className="hidden min-w-0 flex-1 rounded border border-border bg-bg3 px-3 py-1 font-mono text-[11px] uppercase tracking-wider text-textmid outline-none placeholder:text-textdim focus:border-gold sm:block"
          />
          <StatusDot status={status} lastHeartbeat={state?.last_heartbeat} />
          <Clock />
          <ThemeToggle />
          {!isPhone && (
            <button onClick={toggleFullscreen} title="Fullscreen terminal" className="rounded border border-border px-2 py-1 font-mono text-[12px] text-textmid transition hover:border-gold hover:text-gold">⛶</button>
          )}
        </header>

        {/* ── Body ── */}
        <div className="relative flex min-h-0 flex-1">
          {/* Sidebar — overlay on small screens so it doesn't eat canvas width */}
          {sidebarOpen ? (
            <>
              {isSmall && <div className="absolute inset-0 z-30 bg-black/50" onClick={() => setSidebarOpen(false)} />}
            <aside className={`flex w-56 flex-col border-r border-border bg-bg2 ${isSmall ? "absolute left-0 top-0 bottom-0 z-40" : "shrink-0"}`}>
              <div className="flex items-center justify-between border-b border-border px-3 py-2">
                <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-gold">{view === "terminal" ? "Widgets" : "Algorithms"}</span>
                <button onClick={() => setSidebarOpen(false)} title="Hide sidebar" className="px-1 font-mono text-textdim hover:text-gold">‹</button>
              </div>
              {view === "terminal" ? (
                <>
                  <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="search…" className="m-2 rounded border border-border bg-bg3 px-2 py-1.5 font-mono text-[11px] text-textmid outline-none focus:border-gold" />
                  <div className="min-h-0 flex-1 overflow-y-auto pb-2">
                    {catalog.map((cat) => (
                      <div key={cat.name} className="mb-1">
                        <div className="px-3 py-1 font-mono text-[9px] uppercase tracking-[0.2em] text-textdim">{cat.name}</div>
                        {cat.items.map((w) => (
                          <button
                            key={w.id}
                            draggable
                            onDragStart={(e) => {
                              e.dataTransfer.setData("application/apex-widget", w.id);
                              e.dataTransfer.effectAllowed = "copy";
                              // Carry a little "tab" chip on the cursor.
                              const ghost = document.createElement("div");
                              ghost.textContent = `${w.code}  ${w.name}`;
                              ghost.style.cssText = "position:absolute;top:-1000px;left:-1000px;padding:7px 12px;background:#1b1b1f;border:1px solid #c9a84c;border-radius:8px;color:#c9a84c;font:600 12px 'DM Mono',monospace;box-shadow:0 8px 24px rgba(0,0,0,.6)";
                              document.body.appendChild(ghost);
                              e.dataTransfer.setDragImage(ghost, 12, 12);
                              setTimeout(() => document.body.removeChild(ghost), 0);
                            }}
                            onDragEnd={() => { setDragOver(false); setSnapZone(null); }}
                            onClick={() => { addWidget(w.id); if (isSmall) setSidebarOpen(false); }}
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
                </>
              ) : (
                <div className="min-h-0 flex-1 overflow-y-auto p-3 text-[12px] leading-relaxed text-textmid">
                  <div className="mb-2 font-mono text-[9px] uppercase tracking-[0.2em] text-textdim">Guide</div>
                  <p className="mb-3">Backtest a strategy on <span className="text-gold">20 years</span> of local daily data — fully offline.</p>
                  <ul className="space-y-2">
                    <li><span className="text-gold">Single</span> — pick an algorithm (right), set instrument &amp; bars, then <span className="text-gold">Run</span>. The replay animates bar-by-bar; metrics track the replay time.</li>
                    <li><span className="text-gold">Compare</span> — overlay several algorithms' equity curves on one chart to see which compounds best.</li>
                    <li><span className="text-gold">+ Create</span> — write a custom Python strategy. It auto-saves after your first save and runs on the local data.</li>
                  </ul>
                  <p className="mt-3 text-[11px] text-textdim">Local data: US500, FTSE100, EURUSD · vars include fear &amp; greed, VIX, sentiment.</p>
                </div>
              )}
              {/* bottom: settings + sign out */}
              <div className="border-t border-border p-2">
                <Link href="/settings" className="mb-2 flex items-center gap-2 rounded px-2 py-1.5 text-[12px] text-textmid transition hover:bg-bg3 hover:text-gold">
                  <span className="rounded bg-gold/10 px-1 py-0.5 font-mono text-[9px] text-gold">SET</span> Settings
                </Link>
                <SignOutButton />
              </div>
            </aside>
            </>
          ) : (
            <button onClick={() => setSidebarOpen(true)} title="Show sidebar" className="flex w-6 shrink-0 items-center justify-center border-r border-border bg-bg2 transition hover:bg-bg3">
              <span className="font-mono text-[9px] uppercase tracking-[0.3em] text-gold" style={{ writingMode: "vertical-rl" }}>› {view === "terminal" ? "Widgets" : "Menu"}</span>
            </button>
          )}

          {/* Canvas / Backtest */}
          <main
            ref={mainRef}
            className="relative min-h-0 flex-1"
            onDragOver={(e) => {
              const types = e.dataTransfer.types;
              if (types.includes("application/apex-dock")) {
                e.preventDefault(); e.dataTransfer.dropEffect = "move";
                const rect = mainRef.current?.getBoundingClientRect();
                if (rect) {
                  const rx = (e.clientX - rect.left) / rect.width, ry = (e.clientY - rect.top) / rect.height;
                  setSnapZone(rx <= 0.15 ? "left" : rx >= 0.85 ? "right" : ry <= 0.15 ? "top" : ry >= 0.85 ? "bottom" : null);
                }
              } else if (types.includes("application/apex-widget")) {
                e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setDragOver(true);
              }
            }}
            onDragLeave={(e) => { if (e.currentTarget === e.target) { setDragOver(false); setSnapZone(null); } }}
            onDrop={onDropWidget}
          >
            {view === "terminal" && (
              <ReactFlow
                nodes={nodes}
                edges={[]}
                onNodesChange={onNodesChange}
                onInit={(inst) => { rfRef.current = inst; }}
                onMoveStart={startInteract}
                onMoveEnd={(e) => endInteract(e)}
                onNodeDragStart={(_e, node) => { startInteract(); draggedIdRef.current = node.id; dragEdgeRef.current = undefined; clearDragTimer(); stopAutoPan(); }}
                onNodeDrag={(e) => onNodeDrag(e)}
                onNodeDragStop={onNodeDragStop}
                onPaneClick={deselectAll}
                nodeTypes={nodeTypes}
                proOptions={{ hideAttribution: true }}
                minZoom={0.25}
                maxZoom={2}
                fitView
                fitViewOptions={{ maxZoom: 1, padding: 0.12 }}
                panOnDrag
                zoomOnScroll
                autoPanOnNodeDrag={false}
                selectionOnDrag={false}
                deleteKeyCode={null}
              >
                <Background id="lines" variant={BackgroundVariant.Lines} gap={66} size={1} color={grid.lines} />
                <Background id="dots" variant={BackgroundVariant.Dots} gap={22} size={1} color={grid.dots} />
                <Controls showInteractive={false} />
                {interacting && (
                  <MiniMap
                    pannable zoomable nodeColor="#c9a84c66" nodeStrokeColor="#c9a84c"
                    maskColor={light ? "rgba(0,0,0,0.15)" : "rgba(0,0,0,0.6)"}
                    style={isSmall ? { width: 96, height: 64 } : undefined}
                  />
                )}
              </ReactFlow>
            )}
            {/* BacktestTab stays mounted (hidden when on Terminal) so its results
                survive tab swaps — only a full page reset clears them. */}
            <div className={`absolute inset-0 overflow-auto p-4 ${view === "backtest" ? "" : "hidden"}`}>
              <BacktestTab />
            </div>

            {/* Docked panels (fixed to the edges, stay put while the canvas pans).
                Left/right run full height; top/bottom sit between them. */}
            {view === "terminal" && dockPanel("left")}
            {view === "terminal" && dockPanel("right")}
            {view === "terminal" && dockPanel("top")}
            {view === "terminal" && dockPanel("bottom")}

            {/* Snap preview while dragging toward an edge — outline matches the exact
                flush area the docked panel will occupy. */}
            {view === "terminal" && snapZone && (
              <div
                className="pointer-events-none absolute z-40 border-2 border-dashed border-gold/80"
                style={dockGeom(snapZone)}
              />
            )}

            {/* Subtle outline while dragging a widget in from the sidebar */}
            {dragOver && view === "terminal" && (
              <div className="pointer-events-none absolute inset-2 z-10 rounded-lg border-2 border-dashed border-gold/50" />
            )}

            {/* Maximize overlay: fills the canvas region, leaves pan/zoom untouched */}
            {view === "terminal" && maximizedId && (() => {
              const inst = nodes.find((n) => n.id === maximizedId);
              const def = inst && WIDGETS_BY_ID[inst.data.widgetId];
              if (!def) return null;
              return (
                // Fill only the space NOT taken by docked panels (all four sides), flush
                // to them, so docked windows stay visible alongside the maximized one.
                <div
                  className="absolute z-30 bg-bg"
                  style={{
                    left: dock.left ? `${dock.leftW}%` : 0,
                    right: dock.right ? `${dock.rightW}%` : 0,
                    top: dock.top ? `${dock.topH}%` : 0,
                    bottom: dock.bottom ? `${dock.bottomH}%` : 0,
                  }}
                >
                  <div className="apex-window h-full w-full overflow-hidden" style={{ borderRadius: 0 }}>
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
        <footer className="flex items-center gap-1 overflow-x-auto border-t border-border bg-bg2 px-2 py-1">
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

        {/* In-app confirm dialog for Clear / Reset (styled like the Sign-out modal). */}
        {confirmDlg && (
          <div
            className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4"
            onClick={() => setConfirmDlg(null)}
          >
            <div
              className="w-full max-w-sm rounded-md border border-border bg-bg2 p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.3em] text-gold">Apex Algo</div>
              <h2 className="mb-2 text-lg font-bold">{confirmDlg.title}</h2>
              <p className="mb-6 text-sm text-textmid">{confirmDlg.message}</p>
              <div className="flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setConfirmDlg(null)}
                  className="rounded border border-border px-4 py-2 font-mono text-[11px] uppercase tracking-wider text-textmid transition hover:border-gold hover:text-gold"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => { confirmDlg.onConfirm(); setConfirmDlg(null); }}
                  className="rounded bg-gold px-4 py-2 text-sm font-bold text-black transition hover:bg-gold2"
                >
                  {confirmDlg.confirmLabel}
                </button>
              </div>
            </div>
          </div>
        )}
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

function StatusDot({ status, lastHeartbeat }: { status: string; lastHeartbeat?: string }) {
  // "Engine" = is the laptop/backend actively pushing heartbeats? The state can be
  // served stale from KV after the engine stops, so freshness is judged by the
  // heartbeat age, not just whether the fetch succeeded.
  const ageMs = lastHeartbeat ? Date.now() - Date.parse(lastHeartbeat) : Infinity;
  const live = status === "live" && Number.isFinite(ageMs) && ageMs < 120_000;
  const title = lastHeartbeat
    ? `Engine ${live ? "running" : "offline"} · last heartbeat ${new Date(lastHeartbeat).toLocaleTimeString()}`
    : "Engine offline — backend not running";
  return (
    <span className="hidden items-center gap-1.5 font-mono text-[10px] text-textdim sm:flex" title={title}>
      <span className={`h-1.5 w-1.5 rounded-full ${live ? "bg-up" : "bg-down"} ${live ? "animate-pulse" : ""}`} />
      Engine
    </span>
  );
}
