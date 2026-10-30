import type { ReactNode } from "react";

import { Seal } from "@/components/ui/seal";

/**
 * 登录/注册页：书封。
 * 左侧是竖排的书名与钤印，右侧是表单——md 以下书名转为横排，不至于挤掉表单。
 */
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <main className="flex flex-1 items-center justify-center px-5 py-12 sm:px-8">
      <div className="flex w-full max-w-md flex-col items-center gap-10 md:max-w-3xl md:flex-row md:items-center md:justify-center md:gap-20">
        <div className="flex items-center gap-4 md:flex-col md:gap-8">
          <h1 className="font-serif text-2xl tracking-[0.35em] md:title-slip md:text-4xl">
            文境
          </h1>
          <Seal />
        </div>

        <div className="flex w-full max-w-sm flex-col gap-6">
          <div className="flex flex-col gap-1.5 border-b border-rule pb-3">
            <h2 className="text-xl text-ink">{title}</h2>
            <p className="text-sm text-ink-soft">{subtitle}</p>
          </div>
          {children}
        </div>
      </div>
    </main>
  );
}
