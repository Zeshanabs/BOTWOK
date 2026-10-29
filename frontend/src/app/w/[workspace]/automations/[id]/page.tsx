import { AutomationBuilder } from "@/features/automations/components/automation-builder";

export default async function AutomationBuilderPage({ params, searchParams }: { params: Promise<{ workspace: string; id: string }>; searchParams: Promise<{ template?: string }> }) {
  const { id } = await params;
  const { template } = await searchParams;
  return <AutomationBuilder id={id} template={template ?? null} />;
}
