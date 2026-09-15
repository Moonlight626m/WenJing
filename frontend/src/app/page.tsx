import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth-server";
import { roleHome } from "@/lib/role-home";

/** 根路径：已登录按角色落地，未登录去登录页。 */
export default async function Home() {
  const user = await getCurrentUser();
  redirect(user ? roleHome(user.role) : "/login");
}
