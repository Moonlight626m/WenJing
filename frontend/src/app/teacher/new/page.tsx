import { ScriptCreateFlow } from "@/components/teacher/script-create-flow";
import { PageShell } from "@/components/ui/section";
import { requireRole, TEACHER_ROLES } from "@/lib/auth-server";

export const metadata = { title: "新建剧本" };

export default async function NewScriptPage() {
  await requireRole(...TEACHER_ROLES);
  return (
    <PageShell width="max-w-2xl">
      <header className="flex flex-col gap-1.5 border-b border-rule pb-3">
        <h1 className="text-3xl text-ink">新建剧本</h1>
        <p className="measure text-sm text-ink-soft">
          导入一篇课文，编剧 Agent 会分幕、设计角色、写出台词，并在关键节点停下来请你审阅。
        </p>
      </header>
      <ScriptCreateFlow />
    </PageShell>
  );
}
