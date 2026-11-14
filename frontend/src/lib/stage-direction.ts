/**
 * 台词里的舞台提示拆分：`（把橘子堆在皮大衣上）这话我记着` → 动作 + 台词。
 *
 * 运行期角色按提示词习惯把动作写进台词括号（`（动作）台词`），整句直接当字幕
 * 会让人分不清哪句是说出来的。拆开后动作单独一行、台词只留说出口的部分。
 * 后端落库时也会拆一次（`domain/game/speech_text.py`），这里兜住流式文本与
 * 历史消息。
 */

const LEADING = /^\s*[（(]([^（）()]{1,60})[）)]\s*/;
const TRAILING = /\s*[（(]([^（）()]{1,60})[）)]\s*$/;

export interface SpeechParts {
  /** 说出口的台词（已去掉动作括号） */
  text: string;
  /** 舞台提示，多条用「；」连接；没有则为 null */
  direction: string | null;
}

/** 已带结构化 `stage_direction` 的消息直接用；历史消息回退到文本拆分。 */
export function speechParts(
  text: string,
  direction: string | null | undefined
): SpeechParts {
  return direction ? { text, direction } : splitStageDirection(text);
}

export function splitStageDirection(raw: string): SpeechParts {
  const actions: string[] = [];
  let rest = raw;
  let match: RegExpMatchArray | null;
  while ((match = rest.match(LEADING))) {
    actions.push(match[1].trim());
    rest = rest.slice(match[0].length);
  }
  while ((match = rest.match(TRAILING))) {
    actions.push(match[1].trim());
    rest = rest.slice(0, match.index);
  }
  const text = rest.trim();
  // 整句都是动作、没有台词时保持原样，免得字幕只剩一行动作、角色像没说话
  if (!text) return { text: raw.trim(), direction: null };
  return {
    text,
    direction: actions.filter(Boolean).join("；") || null,
  };
}
