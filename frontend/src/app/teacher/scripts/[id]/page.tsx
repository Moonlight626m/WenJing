import { notFound } from "next/navigation";

import { ScriptDetailView } from "@/components/teacher/script-detail-view";
import { requireRole, TEACHER_ROLES } from "@/lib/auth-server";

export default async function ScriptDetailPage(
  props: PageProps<"/teacher/scripts/[id]">
) {
  await requireRole(...TEACHER_ROLES);
  const { id } = await props.params;
  const scriptId = Number(id);
  if (!Number.isInteger(scriptId) || scriptId <= 0) notFound();
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 p-6">
      <ScriptDetailView scriptId={scriptId} />
    </main>
  );
}
