import { AcceptInvite } from "@/features/team/components/accept-invite";

export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <AcceptInvite token={decodeURIComponent(token)} />;
}
