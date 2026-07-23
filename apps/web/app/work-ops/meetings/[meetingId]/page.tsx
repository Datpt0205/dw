import { redirect } from "next/navigation";

export default async function MeetingRedirect({
  params,
}: {
  params: Promise<{ meetingId: string }>;
}) {
  const { meetingId } = await params;
  redirect(`/meetings/${meetingId}`);
}
