"use client";
import { ThemeProvider as NextThemesProvider } from "next-themes";

/** Applies the `.dark` class from the user's choice (persisted by next-themes) or the OS preference. */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange storageKey="botwok-theme">
      {children}
    </NextThemesProvider>
  );
}
