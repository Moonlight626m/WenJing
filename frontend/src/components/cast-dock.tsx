"use client";

import { useId } from "react";

import { useAssetUrl } from "@/lib/asset-url";
import type { CharacterProfile } from "@/lib/contracts/types";
import { initialOf } from "@/lib/stage-cast";
import { Tag } from "@/components/ui/tag";

/** 头像组最多排几位，再多收成「+N」。 */
const MAX_CHIPS = 6;

function CastChip({
  profile,
  isPlayer,
  active,
  speaking,
  playable,
}: {
  profile: CharacterProfile;
  isPlayer: boolean;
  active: boolean;
  speaking: boolean;
  playable: boolean;
}) {
  const { url } = useAssetUrl(profile.avatar_asset);
  const cardId = useId();
  const traits = profile.personality_traits.slice(0, 4).map((t) => t.label);

  return (
    <div className="group relative">
      <button
        type="button"
        aria-label={isPlayer ? `${profile.name}（你）` : profile.name}
        aria-describedby={cardId}
        className={[
          "relative grid size-10 place-items-center overflow-hidden rounded-full border-2 font-serif text-sm",
          "backdrop-blur-md transition-[transform,box-shadow] duration-300 hover:-translate-y-0.5",
          isPlayer
            ? "border-flag bg-flag text-canvas shadow-[0_0_16px_-4px_var(--wj-flag)]"
            : active
              ? "border-glow-jade bg-sunken/70 text-glow-gold shadow-[0_0_18px_-4px_var(--wj-glow-jade)]"
              : "border-glass-edge bg-sunken/70 text-glow-gold",
        ].join(" ")}
      >
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt="" className="h-full w-full object-cover" />
        ) : (
          initialOf(profile.name)
        )}
      </button>
      {speaking && (
        <span
          aria-hidden
          className="animate-voice-ring pointer-events-none absolute inset-0 rounded-full border-2 border-glow-jade"
        />
      )}

      {/* 悬停或键盘聚焦时浮出人物小传 */}
      <div
        id={cardId}
        role="tooltip"
        className="glass invisible absolute top-full left-0 z-30 mt-2 w-64 translate-y-1 rounded-2xl p-3 opacity-0 transition-[opacity,transform,visibility] duration-200 group-focus-within:visible group-focus-within:translate-y-0 group-focus-within:opacity-100 group-hover:visible group-hover:translate-y-0 group-hover:opacity-100"
      >
        <div className="flex items-center gap-2">
          <span className="font-serif text-base text-ink">{profile.name}</span>
          {isPlayer ? (
            <Tag tone="flag">你</Tag>
          ) : playable ? (
            <Tag tone="accent">可扮演</Tag>
          ) : null}
        </div>
        {profile.public_background && (
          <p className="mt-1.5 line-clamp-4 text-xs leading-relaxed text-ink-soft">
            {profile.public_background}
          </p>
        )}
        {traits.length > 0 && (
          <p className="mt-1.5 text-2xs text-glow-gold">{traits.join("、")}</p>
        )}
      </div>
    </div>
  );
}

/**
 * 角色头像组：浮在舞台左上角的一排圆印，你演的角色是朱砂实心，正在说话的人
 * 套一圈青碧光，配音在放时向外扩声纹。悬停或 Tab 聚焦看人物小传，
 * 完整档案在剧情回顾面板的「角色」页。
 */
export function CastDock({
  characters,
  playableRoles,
  playerRole,
  active,
  speaking,
}: {
  characters: CharacterProfile[];
  playableRoles: string[];
  playerRole: string | null;
  active: string | null;
  speaking: readonly string[];
}) {
  if (characters.length === 0) return null;
  const playable = new Set(
    characters.filter((c) => c.is_player_playable.value).map((c) => c.name)
  );
  for (const name of playableRoles) playable.add(name);

  // 你演的角色排第一，其余保持剧本顺序
  const ordered = [
    ...characters.filter((c) => c.name === playerRole),
    ...characters.filter((c) => c.name !== playerRole),
  ];
  const shown = ordered.slice(0, MAX_CHIPS);
  const rest = ordered.length - shown.length;

  return (
    <div className="absolute top-3 left-3 z-20 flex items-center gap-2">
      {shown.map((c) => (
        <CastChip
          key={c.name}
          profile={c}
          isPlayer={c.name === playerRole}
          active={c.name === active}
          speaking={speaking.includes(c.name)}
          playable={playable.has(c.name)}
        />
      ))}
      {rest > 0 && (
        <span className="grid size-10 place-items-center rounded-full border border-glass-edge bg-glass text-xs text-ink-faint backdrop-blur-md">
          +{rest}
        </span>
      )}
    </div>
  );
}
