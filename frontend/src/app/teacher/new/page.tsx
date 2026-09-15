import { ScriptCreateFlow } from "@/components/teacher/script-create-flow";
import { requireRole, TEACHER_ROLES } from "@/lib/auth-server";

export const metadata = { title: "新建剧本 · 文境" };

export default async function NewScriptPage() {
  await requireRole(...TEACHER_ROLES);
  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold tracking-tight">新建剧本</h1>
      <ScriptCreateFlow />
    </main>
  );
}
