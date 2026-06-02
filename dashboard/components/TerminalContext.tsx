"use client";

import { createContext, useContext } from "react";
import type { AlgoState } from "@/lib/types";

type TerminalCtx = {
  state: AlgoState | null;
  removeWidget: (id: string) => void;
  toggleMaximize: (id: string) => void;
  deselectAll: () => void;
  maximizedId: string | null;
};

export const TerminalContext = createContext<TerminalCtx>({
  state: null,
  removeWidget: () => {},
  toggleMaximize: () => {},
  deselectAll: () => {},
  maximizedId: null,
});
export const useTerminal = () => useContext(TerminalContext);
