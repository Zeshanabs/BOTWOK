import { Radar } from "lucide-react";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 p-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2"><Radar className="h-6 w-6 text-primary" /><span className="text-lg font-semibold">Botwok</span></div>
        {children}
      </div>
    </div>
  );
}
