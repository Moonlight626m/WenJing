import { requireRole, STUDENT_ROLES } from "@/lib/auth-server";

export const metadata = { title: "学生空间 · 文境" };

export default async function StudentHome() {
  // page 复查：layout 在客户端导航间不重渲染（Next 鉴权指南），守卫应贴近数据。
  await requireRole(...STUDENT_ROLES);
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold tracking-tight">学生空间</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        剧本广场、详情与游玩将在后续工单（#24）落地。
      </p>
    </main>
  );
}
