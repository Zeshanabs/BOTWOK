import { ReportViewer } from "@/features/reports/components/report-viewer";

export default async function ReportPage({ params }: { params: Promise<{ workspace: string; id: string }> }) {
  const { id } = await params;
  return <ReportViewer id={id} />;
}
