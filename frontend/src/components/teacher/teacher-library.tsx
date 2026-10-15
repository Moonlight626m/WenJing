"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { FormError } from "@/components/auth/form-error";
import { Skeleton, SkeletonCard } from "@/components/skeleton";
import { Button } from "@/components/ui/button";
import { SectionHeading } from "@/components/ui/section";
import { formatApiError, listMyScripts } from "@/lib/api";
import { SCRIPT_STATUS_TONES, scriptStatusLabel, scriptVisibilityLabel } from "@/lib/labels";
import type { ScriptStatus, ScriptSummary } from "@/lib/contracts/types";
import { Tag } from "@/components/ui/tag";

const SECTIONS: { status: ScriptStatus; hint: string }[] = [
  { status: "draft", hint: "待生成或待发布" },
  { status: "published", hint: "已进入学生剧本广场" },
  { status: "unpublished", hint: "已下架，存量世界可继续" },
];

function ScriptCard({ script }: { script: ScriptSummary }) {
  return (
    <Link
      href={`/teacher/scripts/${script.id}`}
      className="flex flex-col gap-1.5 rounded-lg border border-rule bg-surface p-4 transition-colors hover:border-accent"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-serif text-base text-ink">{script.name}</span>
        <Tag tone={SCRIPT_STATUS_TONES[script.status]}>
          {scriptStatusLabel(script.status)}
        </Tag>
        {script.status !== "draft" && (
          <Tag>{scriptVisibilityLabel(script.visibility)}</Tag>
        )}
      </div>
      {script.description && (
        <p className="line-clamp-2 text-xs text-ink-soft">{script.description}</p>
      )}
      <span className="text-2xs text-ink-faint">
        更新于{" "}
        {script.updated_at ? new Date(script.updated_at).toLocaleString() : "—"}
      </span>
    </Link>
  );
}

export function TeacherLibrary() {
  const [items, setItems] = useState<ScriptSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    listMyScripts()
      .then((resp) => {
        if (!active) return;
        setItems(resp.items);
        setError(null);
      })
      .catch((err) => {
        if (!active) return;
        setError(formatApiError(err));
        setItems([]);
      });
    return () => {
      active = false;
    };
  }, [reloadToken]);

  if (error) {
    return (
      <div className="flex flex-col gap-3">
        <FormError message={error} />
        <Button
          tone="outline"
          size="sm"
          className="self-start"
          onClick={() => setReloadToken((n) => n + 1)}
        >
          重试
        </Button>
      </div>
    );
  }

  if (items === null) {
    return (
      <div className="flex flex-col gap-8" aria-label="加载剧本库…" role="status">
        {[0, 1].map((section) => (
          <section key={section} className="flex flex-col gap-3">
            <Skeleton className="h-4 w-32" />
            <div className="grid gap-3 sm:grid-cols-2">
              <SkeletonCard lines={2} />
              <SkeletonCard lines={2} />
            </div>
          </section>
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      {items.length === 0 && (
        <p className="measure text-sm text-ink-soft">
          还没有剧本。点右上角「新建剧本」，导入课文后即可生成。
        </p>
      )}

      {SECTIONS.map(({ status, hint }) => {
        const group = items.filter((item) => item.status === status);
        return (
          <section key={status} className="flex flex-col gap-3">
            <SectionHeading
              title={scriptStatusLabel(status)}
              meta={`${group.length} 篇`}
              action={<span className="text-xs text-ink-faint">{hint}</span>}
            />
            {group.length === 0 ? (
              <p className="text-xs text-ink-faint">暂无</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {group.map((script) => (
                  <ScriptCard key={script.id} script={script} />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
