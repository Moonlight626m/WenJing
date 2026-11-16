"use client";

import { useId } from "react";

import { useAssetUrl } from "@/lib/asset-url";
import { useCastRoster } from "@/lib/cast-roster";
import type { CharacterProfile } from "@/lib/contracts/types";
import { useSpeakingSpeakers } from "@/lib/audio-session";
import { initialOf } from "@/lib/stage-cast";
import { useGameStore } from "@/stores/gameStore";
import { Tag } from "@/components/ui/tag";

/** 头像组最多排几位，再多收成「+N」。 */
const MAX_CHIPS = 6;

function CastChip({
  profile,
  isPlayer,
  active,
  speaking,
  playable,
  present,
  dynamic,
}: {
  profile: CharacterProfile;
  isPlayer: boolean;
  active: boolean;
  speaking: boolean;
  playable: boolean;
  present: boolean;
  dynamic: boolean;
}) {
  const { url } = useAssetUrl(profile.avatar_asset);
  const cardId = useId();
  const traits = profile.personality_traits.slice(0, 4).map((t) => t.label);

  return (
    <div className="group relative">
      <button
        type="button"
        aria-label={`${isPlayer ? `${profile.name}（你）` : profile.name}${
          present ? "" : "（不在场）"
        }`}
        aria-describedby={cardId}
        className={[
          "relative grid size-10 place-items-center overflow-hidden rounded-full border-2 font-serif text-sm",
          "backdrop-blur-md transition-[transform,box-shadow,opacity] duration-300 hover:-translate-y-0.5",
          present ? "opacity-100" : "opacity-40",
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
          {dynamic && <Tag>运行期登场</Tag>}
          {!present && <Tag>不在场</Tag>}
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
 * 角色头像组：侧栏里的在场名单。你演的角色是朱砂实心，正在说话的人套一圈青碧光，
 * 配音在放时向外扩声纹。悬停或 Tab 聚焦看人物小传，完整档案在侧栏「角色」页。
 *
 * 从舞台左上角挪进侧栏：头像浮在背景上会被误当成场景的一部分。
 */
export function CastDock() {
  const { listed: characters, dynamic, presentNames: present, cast } = useCastRoster();
  const speaking = useSpeakingSpeakers();
  const playableRoles = useGameStore((s) => s.playableRoles);
  const playerRole = useGameStore((s) => s.playerRole);
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
  // 玩家永远在当前地点；运行期拉入/新增的角色已经并入服务端下发的
  // `scene_options[].participants`，所以这里不再为 `dynamic` 开例外——
  // 否则在别处的新角色也会一直亮着，和「当前在场」那一行自相矛盾。
  const isPresent = (name: string) =>
    name === playerRole || (present ? present.has(name) : true);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {shown.map((c) => (
        <CastChip
          key={c.name}
          profile={c}
          isPlayer={c.name === playerRole}
          active={c.name === cast.active}
          speaking={speaking.includes(c.name)}
          playable={playable.has(c.name)}
          present={isPresent(c.name)}
          dynamic={dynamic.has(c.name)}
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
