import Link from "next/link";

import { TeacherLibrary } from "@/components/teacher/teacher-library";
import { requireRole, TEACHER_ROLES } from "@/lib/auth-server";

export const metadata = { title: "教师工作台 · 文境" };

export default async function TeacherHome() {
  // page 复查：layout 在客户端导航间不重渲染（Next 鉴权指南），守卫应贴近数据。
  await requireRole(...TEACHER_ROLES);
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">教师工作台</h1>
        <Link
          href="/teacher/new"
          className="rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 dark:bg-zinc-100 dark:text-black"
        >
          新建剧本
        </Link>
      </header>
      <TeacherLibrary />
    </main>
  );
}
