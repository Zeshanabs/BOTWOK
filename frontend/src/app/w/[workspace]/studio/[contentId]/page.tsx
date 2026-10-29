import { Suspense } from "react";
import { ContentEditor } from "@/features/studio/components/content-editor";

export default async function StudioEditorPage({ params }: { params: Promise<{ workspace: string; contentId: string }> }) {
  const { contentId } = await params;
  return (
    <Suspense fallback={<div className="text-sm text-muted-foreground">Loading editor…</div>}>
      <ContentEditor contentId={contentId} />
    </Suspense>
  );
}
