import type { CharacterProfile } from "@/lib/contracts/types";
import type { ChatMessage, LiveStream } from "@/stores/gameStore";

/** 同时站在台上的立绘上限：再多就挤，三个是视觉小说的常见上限。 */
export const MAX_ON_STAGE = 3;

export interface StageCast {
  /** 台上的角色，按在这一段里首次开口的先后排（位置稳定，不随谁说话而跳） */
  onStage: string[];
  /** 此刻在说话的角色；旁白时为 null，台上的人一起退暗 */
  active: string | null;
}

/**
 * 从消息流与在途流推出「台上有谁、谁在说」。
 *
 * 台上的人取最近开口的 {@link MAX_ON_STAGE} 位（在途流算最新）；说话人优先取还在流式
 * 生成的那一路，否则看最后一条非系统消息是不是台词。纯函数，便于不起浏览器断言。
 */
export function stageCast(
  messages: ChatMessage[],
  streams: LiveStream[],
  limit = MAX_ON_STAGE
): StageCast {
  const recent: string[] = [];
  const note = (name: string | null) => {
    if (name && !recent.includes(name) && recent.length < limit) recent.push(name);
  };

  const live = streams.filter((s) => !s.ended);
  for (let i = live.length - 1; i >= 0; i--) note(live[i].speaker);
  for (let i = messages.length - 1; i >= 0 && recent.length < limit; i--) {
    const m = messages[i];
    if (m.kind === "character_speech") note(m.speaker);
  }

  let active: string | null = live.length > 0 ? live[live.length - 1].speaker : null;
  if (!active) {
    for (let i = messages.length - 1; i >= 0; i--) {
      const m = messages[i];
      if (m.kind === "system") continue;
      active = m.kind === "character_speech" ? m.speaker : null;
      break;
    }
  }

  return { onStage: recent.reverse(), active };
}

/**
 * 侧栏 / 头像组要列的角色：有剧本包就用完整档案，否则（刷新后剧本包还没取回）
 * 退化成只有名字的可扮演角色。
 */
export function listedCharacters(
  characters: CharacterProfile[],
  playableRoles: string[]
): CharacterProfile[] {
  if (characters.length > 0) return characters;
  return playableRoles.map((name) => ({
    name,
    public_background: "",
    personality_traits: [],
    speech_style: null,
    knowledge_boundary: { knows: [], not_knows: [] },
    is_player_playable: { value: true, reason: "" },
  }));
}

/** 名字首字（按字而非码元切），作头像与立牌的印。 */
export function initialOf(name: string): string {
  return Array.from(name)[0] ?? "";
}
