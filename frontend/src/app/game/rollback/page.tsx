"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { RollbackTimeline } from "@/components/rollback/rollback-timeline";
import { PageShell } from "@/components/ui/section";
import { Empty, Loading } from "@/components/ui/states";

function RollbackContent() {
  const sessionId = useSearchParams().get("id");
  if (!sessionId) {
    return (
      <PageShell>
        <Empty
          action={
            <Link href="/student" className="text-sm text-accent underline">
              ← 返回学生空间
            </Link>
          }
        >
          缺少会话参数。
        </Empty>
      </PageShell>
    );
  }
  return <RollbackTimeline sessionId={sessionId} />;
}

export default function RollbackPage() {
  return (
    <Suspense
      fallback={
        <PageShell>
          <Loading label="读取进度…" />
        </PageShell>
      }
    >
      <RollbackContent />
    </Suspense>
  );
}
