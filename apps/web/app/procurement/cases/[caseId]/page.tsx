import { redirect } from "next/navigation";

export default async function CaseRedirect({
  params,
}: {
  params: Promise<{ caseId: string }>;
}) {
  const { caseId } = await params;
  redirect(`/tender/cases/${caseId}`);
}
