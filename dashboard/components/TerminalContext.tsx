"use client";

import { createContext, useContext } from "react";
import type { AlgoState } from "@/lib/types";

type TerminalCtx = {
  state: AlgoState | null;
  removeWidget: (id: string) => void;
};

export const TerminalContext = createContext<TerminalCtx>({ state: null, removeWidget: () => {} });
export const useTerminal = () => useContext(TerminalContext);
