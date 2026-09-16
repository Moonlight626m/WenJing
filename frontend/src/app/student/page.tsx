import { StudentHomeView } from "@/components/student/student-home";
import { requireRole, STUDENT_ROLES } from "@/lib/auth-server";

export const metadata = { title: "学生空间 · 文境" };

export default async function StudentHome() {
  // page 复查：layout 在客户端导航间不重渲染（Next 鉴权指南），守卫应贴近数据。
  await requireRole(...STUDENT_ROLES);
  return <StudentHomeView />;
}
