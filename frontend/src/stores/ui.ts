import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UIState {
  sidebarCollapsed: boolean;
  aiDrawerOpen: boolean;
  theme: "light" | "dark" | "system";
  toggleSidebar: () => void;
  setAiDrawer: (open: boolean) => void;
  setTheme: (t: UIState["theme"]) => void;
}

export const useUI = create<UIState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false, aiDrawerOpen: false, theme: "system",
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setAiDrawer: (open) => set({ aiDrawerOpen: open }),
      setTheme: (theme) => set({ theme }),
    }),
    { name: "botwok-ui" },
  ),
);
