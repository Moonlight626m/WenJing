import { ADMIN_ROLES, requireRole } from "@/lib/auth-server";

export const metadata = { title: "运营后台 · 文境" };

export default async function AdminHome() {
  // page 复查：layout 在客户端导航间不重渲染（Next 鉴权指南），守卫应贴近数据。
  await requireRole(...ADMIN_ROLES);
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-4 p-6">
      <h1 className="text-2xl font-semibold tracking-tight">运营后台</h1>
      <p className="text-sm text-zinc-500 dark:text-zinc-400">
        只读剧本库与 token 用量看板将在后续工单（#25）落地。
      </p>
    </main>
  );
}
