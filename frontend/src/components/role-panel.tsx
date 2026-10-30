"use client";

import type { CharacterProfile } from "@/lib/contracts/types";
import { Tag } from "@/components/ui/tag";

/**
 * 在场角色（侧栏）。朱砂标"你"——与舞台上其他角色名同一个语义：
 * 朱砂只表示"在场"，不作装饰色。
 */
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

  if (listed.length === 0) {
    return <p className="text-xs text-ink-faint">尚未登场。</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {listed.map((c) => {
        const isPlayer = c.name === playerRole;
        return (
          <div
            key={c.name}
            className={`rounded-md border px-3 py-2.5 ${
              isPlayer
                ? "border-flag/50 bg-flag-wash"
                : "border-rule bg-panel"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-serif text-base text-ink">{c.name}</span>
              {isPlayer ? (
                <Tag tone="flag">你</Tag>
              ) : playableSet.has(c.name) ? (
                <Tag tone="accent">可扮演</Tag>
              ) : null}
            </div>
            {c.public_background && (
              <p className="mt-1.5 line-clamp-4 text-xs leading-relaxed text-ink-faint">
                {c.public_background}
              </p>
            )}
            {c.personality_traits.length > 0 && (
              <p className="mt-1.5 text-2xs text-ink-faint">
                {c.personality_traits
                  .slice(0, 4)
                  .map((t) => t.label)
                  .join("、")}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
