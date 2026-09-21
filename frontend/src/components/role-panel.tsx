"use client";

import type { CharacterProfile } from "@/lib/contracts/types";

/** 角色面板：剧本角色卡（可扮演标记）+ 玩家当前角色高亮。 */
export function RolePanel({
  characters,
  playableRoles,
  playerRole,
}: {
  characters: CharacterProfile[];
  playableRoles: string[];
  playerRole: string | null;
}) {
  const listed =
    characters.length > 0
      ? characters
      : playableRoles.map((name) => ({
          name,
          public_background: "",
          personality_traits: [],
          speech_style: null,
          knowledge_boundary: { knows: [], not_knows: [] },
          is_player_playable: { value: true, reason: "" },
        }));
  const playableSet = new Set(
    characters.filter((c) => c.is_player_playable.value).map((c) => c.name)
  );
  for (const name of playableRoles) playableSet.add(name);

  return (
    <div className="flex flex-col gap-3">
      {listed.map((c) => {
        const isPlayer = c.name === playerRole;
        return (
          <div
            key={c.name}
            className={`rounded-lg border p-3 text-sm ${
              isPlayer
                ? "border-emerald-400 bg-emerald-50 dark:border-emerald-700 dark:bg-emerald-950/40"
                : "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{c.name}</span>
              {playableSet.has(c.name) && (
                <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] text-blue-700 dark:bg-blue-900/60 dark:text-blue-300">
                  可扮演
                </span>
              )}
            </div>
            {isPlayer && (
              <div className="mt-1 text-[10px] text-emerald-600 dark:text-emerald-400">
                你正扮演此角色
              </div>
            )}
            {c.public_background && (
              <p className="mt-2 line-clamp-4 text-xs text-zinc-500 dark:text-zinc-400">
                {c.public_background}
              </p>
            )}
            {c.personality_traits.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {c.personality_traits.slice(0, 4).map((t) => (
                  <span
                    key={t.label}
                    className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                  >
                    {t.label}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
