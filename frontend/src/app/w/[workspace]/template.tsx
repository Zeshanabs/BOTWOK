import { CommandPalette } from "@/components/layout/command-palette";

/** Mounts workspace-wide client overlays (⌘K palette) without touching the AppShell. */
export default function WorkspaceTemplate({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <CommandPalette />
    </>
  );
}
