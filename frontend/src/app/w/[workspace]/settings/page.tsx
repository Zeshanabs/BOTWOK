import { redirect } from "next/navigation";

export default async function SettingsIndex({ params }: { params: Promise<{ workspace: string }> }) {
  const { workspace } = await params;
  redirect(`/w/${workspace}/settings/brand`);
}
