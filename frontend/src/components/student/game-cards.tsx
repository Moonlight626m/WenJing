"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Tag } from "@/components/ui/tag";
import { scriptVisibilityLabel, stageLabel } from "@/lib/labels";
import { routeForStage } from "@/lib/session-cache";
import type { ScriptGameGroup } from "@/lib/session-groups";
import type { ScriptSummary, SessionSummary } from "@/lib/contracts/types";

/** 会话/剧本的本地时间；缺失时占位，避免行内出现 Invalid Date。 */
function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

/**
 * 单局游戏行（剧本页 / 无归属旧会话）。`title` 替换默认的剧本名——
 * 剧本详情页里标题已是剧本名，行内改标「第 N 局」。
 */
export function GameRow({
  session,
  title,
}: {
  session: SessionSummary;
  title?: string;
}) {
  const router = useRouter();
  const ended = session.stage === "ended";
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-5 gap-y-3 rounded-lg border border-rule bg-surface px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-serif text-base text-ink">
            {title ?? session.script_name ?? "（旧会话）"}
          </span>
          <Tag>{stageLabel(session.stage)}</Tag>
        </div>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-ink-faint">
          <span>{session.player_role ? `扮演 ${session.player_role}` : "未选角"}</span>
          <span className="font-mono">{formatTime(session.updated_at)}</span>
        </p>
      </div>
      <Button
        tone={ended ? "outline" : "accent"}
        size="sm"
        onClick={() =>
          router.push(
            routeForStage(
              session.session_id,
              session.stage,
              session.player_role,
              session.script_id
            )
          )
        }
      >
        {ended ? "查看" : "继续"}
      </Button>
    </li>
  );
}

/** 剧本卡：「我的游戏」的列表单位——一部戏一行，点进去看这部剧的各局。 */
export function ScriptGameCard({ group }: { group: ScriptGameGroup }) {
  const latest = group.sessions[0];
  const roles = [
    ...new Set(
      group.sessions
        .map((session) => session.player_role)
        .filter((role): role is string => Boolean(role))
    ),
  ];
  return (
    <li>
      <Link
        href={`/student/scripts/${group.scriptId}`}
        className="flex flex-wrap items-center justify-between gap-x-5 gap-y-3 rounded-lg border border-rule bg-surface px-4 py-3 transition-colors hover:border-accent"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-serif text-base text-ink">
              {group.scriptName ?? "（剧本已删除）"}
            </span>
            <Tag>{stageLabel(latest.stage)}</Tag>
            <Tag tone={group.sessions.length > 1 ? "accent" : "neutral"}>
              {group.sessions.length} 局
            </Tag>
          </div>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-ink-faint">
            <span>
              {roles.length > 0 ? `扮演过 ${roles.join(" / ")}` : "未选角"}
            </span>
            <span className="font-mono">{formatTime(latest.updated_at)}</span>
          </p>
        </div>
        <span className="text-sm text-accent">查看剧本</span>
      </Link>
    </li>
  );
}

/** 剧本广场卡。 */
export function SquareCard({ script }: { script: ScriptSummary }) {
  return (
    <Link
      href={`/student/scripts/${script.id}`}
      className="flex flex-col gap-1.5 rounded-lg border border-rule bg-surface p-4 transition-colors hover:border-accent"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-serif text-base text-ink">{script.name}</span>
        <Tag>{scriptVisibilityLabel(script.visibility)}</Tag>
      </div>
      {script.description && (
        <p className="line-clamp-2 text-xs text-ink-soft">{script.description}</p>
      )}
      <span className="text-2xs text-ink-faint">
        更新于 {formatTime(script.updated_at)}
      </span>
    </Link>
  );
}
