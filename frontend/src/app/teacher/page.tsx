import Link from "next/link";

import { TeacherLibrary } from "@/components/teacher/teacher-library";
import { buttonClass } from "@/components/ui/button";
import { PageShell } from "@/components/ui/section";
import { requireRole, TEACHER_ROLES } from "@/lib/auth-server";

export const metadata = { title: "教师工作台" };

export default async function TeacherHome() {
  // page 复查：layout 在客户端导航间不重渲染（Next 鉴权指南），守卫应贴近数据。
  await requireRole(...TEACHER_ROLES);
  return (
    <PageShell width="max-w-4xl">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-rule pb-3">
        <h1 className="text-3xl text-ink">教师工作台</h1>
        <Link href="/teacher/new" className={buttonClass("accent", "sm")}>
          新建剧本
        </Link>
      </header>
      <TeacherLibrary />
    </PageShell>
  );
}
