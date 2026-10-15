"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import { Button } from "@/components/ui/button";
import { TextInput } from "@/components/ui/field";
import { PageShell, SectionHeading } from "@/components/ui/section";
import { Empty, Loading } from "@/components/ui/states";
import { Tag } from "@/components/ui/tag";
import { formatApiError, listMySessions, listSquareScripts } from "@/lib/api";
import { scriptVisibilityLabel, stageLabel } from "@/lib/labels";
import { routeForStage } from "@/lib/session-cache";
import type { ScriptSummary, SessionSummary } from "@/lib/contracts/types";

function GameRow({ session }: { session: SessionSummary }) {
  const router = useRouter();
  const ended = session.stage === "ended";
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-5 gap-y-3 rounded-lg border border-rule bg-surface px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-serif text-base text-ink">
            {session.script_name ?? "（旧会话）"}
          </span>
          <Tag>{stageLabel(session.stage)}</Tag>
        </div>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-ink-faint">
          <span>{session.player_role ? `扮演 ${session.player_role}` : "未选角"}</span>
          <span className="font-mono">
            {session.updated_at
              ? new Date(session.updated_at).toLocaleString()
              : "—"}
          </span>
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

function SquareCard({ script }: { script: ScriptSummary }) {
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
        更新于{" "}
        {script.updated_at ? new Date(script.updated_at).toLocaleString() : "—"}
      </span>
    </Link>
  );
}

export function StudentHomeView() {
  const [games, setGames] = useState<SessionSummary[] | null>(null);
  const [gamesError, setGamesError] = useState<string | null>(null);
  const [square, setSquare] = useState<ScriptSummary[] | null>(null);
  const [squareError, setSquareError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let active = true;
    listMySessions()
      .then((resp) => {
        if (active) setGames(resp.items);
      })
      .catch((err) => {
        if (active) {
          setGamesError(formatApiError(err));
          setGames([]);
        }
      });
    listSquareScripts()
      .then((resp) => {
        if (active) setSquare(resp.items);
      })
      .catch((err) => {
        if (active) {
          setSquareError(formatApiError(err));
          setSquare([]);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const base = square ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return base;
    return base.filter(
      (script) =>
        script.name.toLowerCase().includes(q) ||
        (script.description ?? "").toLowerCase().includes(q)
    );
  }, [square, query]);

  return (
    <PageShell>
      <h1 className="text-3xl text-ink">学生空间</h1>

      <section className="flex flex-col gap-4">
        <SectionHeading title="我的游戏" meta={games ? `${games.length} 局` : undefined} />
        {gamesError && <FormError message={gamesError} />}
        {games === null ? (
          <Loading />
        ) : games.length === 0 ? (
          <Empty>还没有游戏。从下面的剧本广场挑一篇课文开始。</Empty>
        ) : (
          <ul className="flex flex-col gap-2">
            {games.map((session) => (
              <GameRow key={session.session_id} session={session} />
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeading
          title="剧本广场"
          meta={square ? `${filtered.length} 篇` : undefined}
          action={
            <TextInput
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索课文或简介"
              aria-label="搜索剧本"
              controlSize="sm"
              className="w-52"
            />
          }
        />
        {squareError && <FormError message={squareError} />}
        {square === null ? (
          <Loading />
        ) : filtered.length === 0 ? (
          <Empty>
            {query
              ? "没有匹配的剧本，换个词试试。"
              : "暂时没有可游玩的剧本，等老师发布后会出现在这里。"}
          </Empty>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {filtered.map((script) => (
              <SquareCard key={script.id} script={script} />
            ))}
          </div>
        )}
      </section>
    </PageShell>
  );
}
