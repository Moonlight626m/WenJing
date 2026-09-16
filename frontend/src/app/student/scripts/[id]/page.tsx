import { notFound } from "next/navigation";

import { StudentScriptDetail } from "@/components/student/student-script-detail";
import { requireRole, STUDENT_ROLES } from "@/lib/auth-server";

export const metadata = { title: "剧本详情 · 文境" };

export default async function StudentScriptPage({
  params,
}: PageProps<"/student/scripts/[id]">) {
  // page 复查：layout 在客户端导航间不重渲染（Next 鉴权指南），守卫应贴近数据。
  await requireRole(...STUDENT_ROLES);
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  return <StudentScriptDetail scriptId={Number(id)} />;
}
