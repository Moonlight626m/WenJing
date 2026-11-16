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
 *
 * 给了 `present`（当前地点在场名单）时只留**在场**的人：换景之后上一幕的人不该还站在
 * 台上，否则和侧栏名册、交互卡的「当前在场」互相矛盾。旁白或无人在场时 `active` 为 null。
 */
export function stageCast(
  messages: ChatMessage[],
  streams: LiveStream[],
  present: ReadonlySet<string> | null = null,
  limit = MAX_ON_STAGE
): StageCast {
  const recent: string[] = [];
  const note = (name: string | null) => {
    if (!name || (present && !present.has(name))) return;
    if (!recent.includes(name) && recent.length < limit) recent.push(name);
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
  if (active && present && !present.has(active)) active = null;

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

/** 运行期登场的角色：档案 + 名字集合（后者用于「运行期登场」标记）。 */
export interface RuntimeCast {
  characters: CharacterProfile[];
  dynamic: Set<string>;
}

const CREATED_RE = /^新角色「([^」]+)」登场[：:]?(.*)$/;
const PULLED_RE = /^「([^」]+)」来到了现场(?:[：:](.*))?。?$/;

/**
 * 把消息流里出现的运行期角色补进角色表（M6 动态角色）。
 *
 * 后端目前只把 `character_created` / `pull_in_character` 投影成系统文本，
 * 还没有结构化档案；这里按**固定的两种文案**提取名字，再合并台词里出现过的
 * speaker。属于过渡方案：payload 带上 `character` 后删掉文本提取，只保留合并。
 */
export function mergeRuntimeCharacters(
  base: CharacterProfile[],
  messages: ChatMessage[],
  playerRole: string | null
): RuntimeCast {
  const known = new Set(base.map((c) => c.name));
  if (playerRole) known.add(playerRole);
  const found = new Map<string, { background: string; traits: string[] }>();

  function note(
    name: string | null | undefined,
    background = "",
    traits: string[] = []
  ) {
    const trimmed = name?.trim();
    if (!trimmed || known.has(trimmed)) return;
    const previous = found.get(trimmed);
    if (!previous) {
      found.set(trimmed, { background, traits });
      return;
    }
    if (!previous.background && background) previous.background = background;
    if (traits.length > 0) previous.traits = traits;
  }

  for (const message of messages) {
    if (message.kind === "character_speech") {
      note(message.speaker);
      continue;
    }
    if (message.kind !== "system") continue;
    // 新投影带结构化 character；旧消息回落到固定文案提取。
    const character = message.character;
    if (character?.name) {
      note(character.name, character.public_background ?? "", character.personality_traits);
      continue;
    }
    const created = CREATED_RE.exec(message.text);
    if (created) {
      note(created[1], created[2].trim());
      continue;
    }
    const pulled = PULLED_RE.exec(message.text);
    if (pulled) note(pulled[1]);
  }

  if (found.size === 0) return { characters: base, dynamic: new Set() };

  const extra: CharacterProfile[] = [...found].map(([name, entry]) => ({
    name,
    public_background: entry.background,
    personality_traits: entry.traits.map((label) => ({
      label,
      evidence: "",
      behavior: "",
    })),
    speech_style: null,
    knowledge_boundary: { knows: [], not_knows: [] },
    is_player_playable: { value: false, reason: "" },
  }));
  return { characters: [...base, ...extra], dynamic: new Set(found.keys()) };
}
