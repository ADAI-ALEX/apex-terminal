"use client";

import { memo } from "react";
import { NodeResizer, type NodeProps } from "reactflow";
import { WIDGETS_BY_ID, WidgetFrame } from "./widgets";
import { useTerminal } from "./TerminalContext";

/** React Flow custom node = one terminal widget window. */
function WidgetNodeImpl({ id, data, selected }: NodeProps<{ widgetId: string }>) {
  const { state, removeWidget, toggleMaximize, deselectAll, maximizedId } = useTerminal();
  const def = WIDGETS_BY_ID[data.widgetId];
  if (!def) return <div className="apex-window h-full w-full" />;
  const maximized = maximizedId === id;

  return (
    <div className="apex-window h-full w-full">
      <NodeResizer
        color="#c9a84c"
        isVisible={selected && !maximized}
        minWidth={def.minW * 60}
        minHeight={def.minH * 24}
      />
      <WidgetFrame
        code={def.code}
        title={def.name}
        onClose={() => removeWidget(id)}
        onMaximize={() => toggleMaximize(id)}
        maximized={maximized}
        // Clicking inside the body interacts with content and exits move/resize mode.
        onBodyPointerDown={(e) => { e.stopPropagation(); deselectAll(); }}
      >
        {state ? (
          def.render(state)
        ) : (
          <div className="flex h-full items-center justify-center font-mono text-[11px] text-textdim">
            waiting for engine…
          </div>
        )}
      </WidgetFrame>
    </div>
  );
}

export const WidgetNode = memo(WidgetNodeImpl);
