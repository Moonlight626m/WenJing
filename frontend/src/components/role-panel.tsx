"use client";

import type { CharacterProfile } from "@/lib/contracts/types";
import { initialOf, listedCharacters } from "@/lib/stage-cast";
import { Tag } from "@/components/ui/tag";

/**
 * 在场角色（剧情回顾面板的「角色」页）。朱砂标"你"，与消息流、字幕里你的名牌同色；其他角色用泥金，
 * 和他们在台词里的名牌对得上。朱砂只表示"在场"，不作装饰色。
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
  const listed = listedCharacters(characters, playableRoles);
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
            className={`rounded-2xl border px-3 py-2.5 backdrop-blur-md ${
              isPlayer
                ? "border-flag/50 bg-flag-wash shadow-[0_0_22px_-8px_var(--wj-flag)]"
                : "border-glass-edge bg-glass"
            }`}
          >
            <div className="flex items-center gap-2.5">
              {/* 名字首字作印：头像资产接入前的占位，也让角色在侧栏里一眼可辨 */}
              <span
                aria-hidden
                className={`grid size-8 shrink-0 place-items-center rounded-full border font-serif text-sm ${
                  isPlayer
                    ? "border-flag/60 bg-flag text-canvas"
                    : "border-glow-gold/45 bg-sunken/60 text-glow-gold"
                }`}
              >
                {initialOf(c.name)}
              </span>
              <span className="min-w-0 flex-1 truncate font-serif text-base text-ink">
                {c.name}
              </span>
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
