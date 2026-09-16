import { AdminDashboard } from "@/components/admin/admin-dashboard";
import { ADMIN_ROLES, requireRole } from "@/lib/auth-server";

export const metadata = { title: "运营后台 · 文境" };

export default async function AdminPage() {
  // page 复查：layout 在客户端导航间不重渲染（Next 鉴权指南），守卫应贴近数据。
  await requireRole(...ADMIN_ROLES);
  return <AdminDashboard />;
}
