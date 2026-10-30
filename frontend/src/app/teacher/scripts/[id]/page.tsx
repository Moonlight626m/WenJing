import { notFound } from "next/navigation";

import { ScriptDetailView } from "@/components/teacher/script-detail-view";
import { PageShell } from "@/components/ui/section";
import { requireRole, TEACHER_ROLES } from "@/lib/auth-server";

export default async function ScriptDetailPage(
  props: PageProps<"/teacher/scripts/[id]">
) {
  await requireRole(...TEACHER_ROLES);
  const { id } = await props.params;
  const scriptId = Number(id);
  if (!Number.isInteger(scriptId) || scriptId <= 0) notFound();
  return (
    <PageShell width="max-w-3xl">
      <ScriptDetailView scriptId={scriptId} />
    </PageShell>
  );
}
