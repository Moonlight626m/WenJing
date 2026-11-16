"use client";

import { useMemo } from "react";

import {
  listedCharacters,
  mergeRuntimeCharacters,
  stageCast,
  type StageCast,
} from "@/lib/stage-cast";
import { useGameStore } from "@/stores/gameStore";

export interface CastRoster {
  cast: StageCast;
  /** 剧本角色 + 运行期登场（带档案或只有名字） */
  listed: ReturnType<typeof listedCharacters>;
  /** 运行期登场的角色名 */
  dynamic: ReadonlySet<string>;
  /** 当前在场名单；null = 没有探索地图（旧剧本/Stage2），不做弱化 */
  presentNames: ReadonlySet<string> | null;
}

/**
 * 游玩页角色名的统一来源：立绘层、侧栏头像组、在场弱化都从这里取，
 * 免得游戏页和侧栏各算一遍、口径慢慢分叉。
 */
export function useCastRoster(): CastRoster {
  const messages = useGameStore((s) => s.messages);
  const streams = useGameStore((s) => s.streams);
  const characters = useGameStore((s) => s.characters);
  const playableRoles = useGameStore((s) => s.playableRoles);
  const playerRole = useGameStore((s) => s.playerRole);
  const interaction = useGameStore((s) => s.interaction);

  const presentNames = useMemo(() => {
    const current = interaction?.scene_options?.find((scene) => scene.is_current);
    if (!current) return null;
    // 玩家永远在场：`participants` 只列 NPC（交互卡在空表时写「只有你」），
    // 不过滤会把玩家自己的立绘从台上摘掉，和侧栏名册的口径对不上
    return new Set(playerRole ? [...current.participants, playerRole] : current.participants);
  }, [interaction, playerRole]);

  const cast = useMemo(
    () => stageCast(messages, streams, presentNames),
    [messages, streams, presentNames]
  );
  const runtimeCast = useMemo(
    () =>
      mergeRuntimeCharacters(
        listedCharacters(characters, playableRoles),
        messages,
        playerRole
      ),
    [characters, playableRoles, messages, playerRole]
  );

  return {
    cast,
    listed: runtimeCast.characters,
    dynamic: runtimeCast.dynamic,
    presentNames,
  };
}
