/**
 * 演出模式的台本格式。
 *
 * 一份台本 = 一份剧本包（角色、场景、原文证据，和真实系统同一个契约）+ 一张由节点组成的
 * 有向图。每个节点是一串依次播放的「拍」，以抉择、跳转或结局收尾。演出导演
 * （`director.ts`）按台本往 gameStore 灌和真实后端同形的消息，所以舞台渲染的是同一套
 * 游玩页组件，不另做一份界面。
 */
import type { ScriptPackage, StageValue } from "@/lib/contracts/types";

/** 一拍：播完一拍再播下一拍，节奏由导演按字数算，演示者按空格可以跳过等待。 */
export type DemoBeat =
  /** 旁白。带 `scene` 时同时换场（背景、题签、原文对照都跟着走）。 */
  | { t: "narrate"; text: string; scene?: number }
  /** 角色台词，逐字打出（走流式字幕）。 */
  | { t: "say"; who: string; text: string }
  /** 系统消息，出现在剧情回顾里，不上字幕。 */
  | { t: "system"; text: string }
  /** 换阶段：还原 → 还原演完 → 续写 → 结局。 */
  | { t: "stage"; stage: StageValue }
  /** 拾句：课文里的一句原文飞进书匣。 */
  | { t: "quote"; text: string; note: string }
  /** 续写目标：定下这一局要达成的几件事。 */
  | { t: "goals"; goals: string[] }
  /** 达成一个续写目标（从 1 数起）。 */
  | { t: "achieve"; goal: number }
  /** 停一下，给画面留白。 */
  | { t: "wait"; ms: number }
  /** 按记下的标记分支：取 `flags[key]` 对应的节点，取不到走 `fallback`。 */
  | { t: "switch"; key: string; cases: Record<string, string>; fallback: string }
  /** 列出的标记都已设上就跳到 `to`，否则接着往下播。 */
  | { t: "when"; all: string[]; to: string }
  /** 跳到另一个节点。 */
  | { t: "goto"; to: string }
  /** 停在阶段之间，等演示者点「进入剧情续写」。 */
  | { t: "await"; next: string }
  /** 抉择：停下等演示者选，选完按选项跳转。 */
  | DemoChoice
  /** 结局：播完结局画面，本局结束。 */
  | { t: "end"; ending: string };

export interface DemoOption {
  label: string;
  /** 选完由你演的角色说出口的话；不给就不说。 */
  say?: string;
  /** 选完的一句旁白（动作类选项用）。 */
  act?: string;
  /** 抉择卡上标出「谁的主意」。 */
  proposedBy?: string;
  next: string;
  /** 选它时记下的标记（结局与续写开场据此分支）。 */
  set?: Record<string, string>;
  /** 这个标记已设上时不再列出（续写目标达成后对应选项退场）。 */
  hideIf?: string;
}

export interface DemoFreeInput {
  /** 「试试这样说」：点一下就替演示者把这句话发出去。标记已设上的不再列出。 */
  suggestions: { text: string; hideIf?: string }[];
  /** 按关键词把自由输入接到对应节点，从上往下取第一个命中的。 */
  routes: { keywords: string[]; next: string; hideIf?: string }[];
  /** 都没命中时接的节点。 */
  fallback: string;
}

export interface DemoChoice {
  t: "choice";
  id: string;
  prompt: string;
  hint?: string;
  /** 命运抉择：画面褪色、选项落墨，选定后故事走向不同的结局。 */
  fate?: boolean;
  options: DemoOption[];
  /** 允许自己写；不给就只能选。 */
  free?: DemoFreeInput;
}

export interface DemoEnding {
  id: string;
  title: string;
  /** 结局画面的背景图（public 下的路径）。 */
  art: string;
  /** 结局画面上的一段话。 */
  lines: string[];
  /** 没解锁时给的提示。 */
  teaser: string;
}

/**
 * 成就印章：结局时按条件盖上。条件是固定的几种：
 * 演完课文、续写目标全达成、抉择时走出课文之外、回溯过、拾齐原句。
 */
export type DemoSealKind = "restore" | "bond" | "rewrite" | "parallel" | "collect";

export interface DemoSeal {
  id: DemoSealKind;
  /** 印面上的字（两字为宜）。 */
  glyph: string;
  name: string;
  desc: string;
}

export interface DemoScript {
  slug: string;
  /** 书匣上的卷名与小注。 */
  shelf: {
    grade: string;
    source: string;
    minutes: number;
    blurb: string;
    cover: string;
  };
  package: ScriptPackage;
  /** 你演的角色（演出模式只开放一个视角）。 */
  playerRole: string;
  /** 场景背景：scene_id → public 下的图片路径。 */
  backgrounds: Record<number, string>;
  /** 角色立绘：角色名 → public 下的图片路径（没有就退回名牌）。 */
  portraits?: Record<string, string>;
  /** 选角页上每个角色由谁来演的一句话。 */
  castNotes: Record<string, string>;
  /** 课文里能拾到的句子总数（书匣显示「拾得 n/总数」）。 */
  quoteTotal: number;
  nodes: Record<string, DemoBeat[]>;
  start: string;
  /** 「确认结局」与「退出游戏」直接收束到这里。 */
  finale: string;
  endings: DemoEnding[];
  seals: DemoSeal[];
}
