import { redirect } from "next/navigation";

/** Alias for the doc 24 route; the canonical page is /settings/social (OAuth callback target). */
export default async function SocialAccountsAlias({ params, searchParams }: { params: Promise<{ workspace: string }>; searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { workspace } = await params;
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(await searchParams)) {
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else if (v !== undefined) sp.set(k, v);
  }
  const q = sp.toString();
  redirect(`/w/${workspace}/settings/social${q ? `?${q}` : ""}`);
}
