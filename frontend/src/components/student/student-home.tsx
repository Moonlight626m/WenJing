"use client";

import { useEffect, useMemo, useState } from "react";

import { FormError } from "@/components/auth/form-error";
import {
  GameRow,
  ScriptGameCard,
  SquareCard,
} from "@/components/student/game-cards";
import { TextInput } from "@/components/ui/field";
import { PageShell, SectionHeading } from "@/components/ui/section";
import { Empty, Loading } from "@/components/ui/states";
import { formatApiError, listMySessions, listSquareScripts } from "@/lib/api";
import { groupSessionsByScript } from "@/lib/session-groups";
import type { ScriptSummary, SessionSummary } from "@/lib/contracts/types";

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

  const { groups, ungrouped } = useMemo(
    () => groupSessionsByScript(games ?? []),
    [games]
  );

  return (
    <PageShell>
      <h1 className="text-3xl text-ink">学生空间</h1>

      <section className="flex flex-col gap-4">
        <SectionHeading
          title="我的游戏"
          meta={
            games
              ? `${groups.length} 个剧本 · ${games.length} 局`
              : undefined
          }
        />
        {gamesError && <FormError message={gamesError} />}
        {games === null ? (
          <Loading />
        ) : games.length === 0 ? (
          <Empty>还没有游戏。从下面的剧本广场挑一篇课文开始。</Empty>
        ) : (
          <>
            <ul className="flex flex-col gap-2">
              {groups.map((group) => (
                <ScriptGameCard key={group.scriptId} group={group} />
              ))}
            </ul>
            {ungrouped.length > 0 && (
              <ul className="flex flex-col gap-2">
                {ungrouped.map((session) => (
                  <GameRow key={session.session_id} session={session} />
                ))}
              </ul>
            )}
          </>
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
