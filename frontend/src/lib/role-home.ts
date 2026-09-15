import type { UserRole } from "@/lib/contracts/types";

interface RoleMeta {
  home: string;
  label: string;
}

/** 各角色的落地页与展示名（单表，避免 switch 与 label 表各自漂移）。 */
const ROLE_META: Record<UserRole, RoleMeta> = {
  super_admin: { home: "/admin", label: "平台管理员" },
  teacher: { home: "/teacher", label: "教师" },
  student: { home: "/student", label: "学生" },
};

/** 角色默认落地页（登录/注册后跳转、越权重定向共用）。 */
export function roleHome(role: UserRole): string {
  return ROLE_META[role].home;
}

export function roleLabel(role: UserRole): string {
  return ROLE_META[role].label;
}
