import { Suspense } from "react";
import { ContentList } from "@/features/studio/components/content-list";

export default function StudioPage() {
  return (
    <Suspense fallback={<div className="text-sm text-muted-foreground">Loading content…</div>}>
      <ContentList />
    </Suspense>
  );
}
