/**
 * /showcase 界面总览的假数据。
 *
 * 取《故乡》里「少年闰土」那一段，好让画廊里出现的是真读得通的课文内容，
 * 而不是 Lorem ipsum——文案本身也是设计的一部分。
 * 全部数据只在这一个文件里，改版式不必动它，换示意内容也只改这里。
 */
import type {
  ActiveInteraction,
  Stage3Goal,
  AssetRef,
  GenerationProgress,
  GateReview,
  ScriptPackage,
  ScriptSummary,
  SessionSummary,
  UserPublic,
} from "@/lib/contracts/types";
import { CONTRACTS_SCHEMA_VERSION as V } from "@/lib/contracts/types";
import type { ChatMessage, LiveStream, PendingCommand } from "@/stores/gameStore";

const ORG = "f16ca50e-4f13-4a87-985a-38c188495239";

/**
 * 资产槽位。
 *
 * **刻意不给 `status: "ready"`**：`useAssetUrl` 见到 ready 就会去签预签名 URL，
 * 而画廊不登录、后端也不该被它碰到——那一串 401 就是这么来的。给成 pending /
 * failed 反而更诚实：这里本来就没有图，顺带把「缺图优雅降级」的三种形态
 * （生成中 / 生成失败 / 无图不占位）一次演全。
 */
const SLOT = (
  kind: AssetRef["kind"],
  status: AssetRef["status"]
): AssetRef => ({
  asset_id: `00000000-0000-4000-8000-00000000000${kind === "avatar" ? 1 : 2}`,
  kind,
  status,
});

export const USER_TEACHER: UserPublic = {
  schema_version: V,
  id: "9259ae6d-595f-4dac-b830-291634bb4dfd",
  org_id: ORG,
  role: "teacher",
  email: "teacher",
  phone: null,
  nickname: "演示教师",
  created_at: "2026-09-01T08:00:00Z",
};

export const USER_STUDENT: UserPublic = {
  ...USER_TEACHER,
  id: "3a7c1e02-8d44-4f6b-9e10-5c2b7a9d4f13",
  role: "student",
  email: "student",
  nickname: "演示学生",
};

export const USER_ADMIN: UserPublic = {
  ...USER_TEACHER,
  id: "b41d9f77-2c58-4a03-8f6d-7e1a2b3c4d5e",
  role: "super_admin",
  email: "admin",
  nickname: "平台管理员",
};

export const SCRIPT_PACKAGE: ScriptPackage = {
  schema_version: V,
  title: "少年闰土",
  teaching_focus: ["把握人物形象", "梳理叙事线索", "品味关键细节"],
  playable_roles: ["我", "闰土"],
  stage2_ending_beat_id: 5,
  characters: [
    {
      name: "闰土",
      public_background:
        "闰土是忙月的儿子，紫色的圆脸，头戴一顶小毡帽，颈上套一个明晃晃的银项圈。他会装弶捉小鸟雀，能在雪地里捕鸟，也守过西瓜地。",
      personality_traits: [
        { label: "机敏", evidence: "向一匹猹尽力的刺去", behavior: "遇事先动手再解释" },
        { label: "见多识广", evidence: "讲海边拾贝、看瓜", behavior: "说起新鲜事就停不下来" },
      ],
      speech_style: null,
      knowledge_boundary: { knows: ["捕鸟", "看瓜", "海边的贝壳"], not_knows: ["读书", "城里的规矩"] },
      is_player_playable: { value: true, reason: "课文的核心形象，适合学生代入" },
      avatar_asset: SLOT("avatar", "failed"),
      avatar_credit: {
        author: "未知作者",
        license: "CC BY-SA 4.0",
        source_url: "https://example.org/yuntu",
        license_url: "https://creativecommons.org/licenses/by-sa/4.0/",
      },
    },
    {
      name: "我",
      public_background:
        "一个城里的少爷，家中忙月时与闰土相识。向往闰土口中的海边生活，也第一次意识到两人之间的隔膜。",
      personality_traits: [
        { label: "好奇", evidence: "日日盼望新年", behavior: "总在追问细节" },
      ],
      speech_style: null,
      knowledge_boundary: { knows: ["城里的见闻"], not_knows: ["海边的生活"] },
      is_player_playable: { value: true, reason: "叙述者视角，代入感强" },
      avatar_asset: SLOT("avatar", "pending"),
      avatar_credit: {
        author: "未知作者",
        license: "CC0",
        source_url: "",
        license_url: "",
      },
    },
    {
      name: "母亲",
      public_background: "家中长辈，允许闰土来家里管祭器，也是两人得以相识的缘由。",
      personality_traits: [],
      speech_style: null,
      knowledge_boundary: { knows: ["家中事务"], not_knows: ["海边的活计"] },
      is_player_playable: { value: false, reason: "戏份较少，不开放扮演" },
    },
  ],
  scenes: [
    {
      scene_id: 1,
      title: "月下刺猹",
      participants: ["我", "闰土"],
      background_asset: SLOT("background", "pending"),
      background_credit: {
        author: "未知作者",
        license: "CC BY 4.0",
        source_url: "https://example.org/moon",
        license_url: "https://creativecommons.org/licenses/by/4.0/",
      },
      beats: [
        {
          beat_id: 1,
          description: "深蓝的天空中挂着一轮金黄的圆月，下面是海边的沙地。",
          is_key_event: false,
          evidence_refs: [
            { source_type: "original_text", excerpt: "深蓝的天空中挂着一轮金黄的圆月", paragraph_index: 0, char_start: 0, char_end: 18 },
          ],
        },
        {
          beat_id: 2,
          description: "一个十一二岁的少年，项带银圈，手捏一柄钢叉，向一匹猹尽力的刺去。",
          is_key_event: true,
          evidence_refs: [
            { source_type: "original_text", excerpt: "项带银圈，手捏一柄钢叉", paragraph_index: 0, char_start: 30, char_end: 42 },
          ],
        },
      ],
    },
    {
      scene_id: 2,
      title: "雪地捕鸟",
      participants: ["我", "闰土"],
      background_asset: SLOT("background", "failed"),
      beats: [
        {
          beat_id: 3,
          description: "闰土说捕鸟须大雪下了才好，扫开一块雪，支起竹匾。",
          is_key_event: false,
          evidence_refs: [],
        },
        {
          beat_id: 4,
          description: "我日日盼望新年，新年到，闰土也就到了。",
          is_key_event: true,
          evidence_refs: [
            { source_type: "original_text", excerpt: "我于是日日盼望新年", paragraph_index: 1, char_start: 0, char_end: 9 },
          ],
        },
      ],
    },
  ],
};

export const SESSIONS: SessionSummary[] = [
  {
    schema_version: V,
    session_id: "965d173b-99f7-42f1-80b7-497c0b666899",
    script_id: 1,
    script_name: "少年闰土",
    stage: "stage2_reenacting",
    status: "active",
    player_role: "我",
    created_at: "2026-10-15T10:39:06Z",
    updated_at: "2026-10-15T10:52:31Z",
  },
  {
    schema_version: V,
    session_id: "3c1f7a20-5b6e-4d31-9c88-1d2e4f5a6b70",
    script_id: 1,
    script_name: "少年闰土",
    stage: "ended",
    status: "ended",
    player_role: "闰土",
    created_at: "2026-10-11T09:12:00Z",
    updated_at: "2026-10-12T16:04:55Z",
  },
];

export const SQUARE_SCRIPTS: ScriptSummary[] = [
  {
    schema_version: V,
    id: 1,
    name: "少年闰土",
    description: "从《故乡》里截取的少年时光，回到那个月下刺猹的夜晚。",
    status: "published",
    visibility: "org",
    material_id: 1,
    owner_user_id: USER_TEACHER.id,
    org_id: ORG,
    created_at: "2026-10-15T10:39:06Z",
    updated_at: "2026-10-15T10:39:23Z",
  },
  {
    schema_version: V,
    id: 2,
    name: "社戏之夜",
    description: "月夜行船去赵庄看戏，归航时偷罗汉豆的那一段。",
    status: "published",
    visibility: "public",
    material_id: 2,
    owner_user_id: USER_TEACHER.id,
    org_id: ORG,
    created_at: "2026-10-14T15:02:00Z",
    updated_at: "2026-10-14T15:20:10Z",
  },
];

export const MY_SCRIPTS: ScriptSummary[] = [
  SQUARE_SCRIPTS[0],
  {
    ...SQUARE_SCRIPTS[1],
    id: 3,
    name: "背影",
    description: "车站送别，父亲翻过月台去买橘子的那一小段。",
    status: "unpublished",
    updated_at: "2026-10-13T11:45:00Z",
  },
  {
    schema_version: V,
    id: 4,
    name: "桃花源记（草稿）",
    description: null,
    status: "draft",
    visibility: "org",
    material_id: 4,
    owner_user_id: USER_TEACHER.id,
    org_id: ORG,
    created_at: "2026-10-15T11:20:00Z",
    updated_at: "2026-10-15T11:20:00Z",
  },
];

export const MESSAGES: ChatMessage[] = [
  { key: "m1", seq: 1, kind: "system", text: "你将扮演：我", speaker: null },
  { key: "m2", seq: 2, kind: "narrative", text: "深蓝的天空中挂着一轮金黄的圆月，下面是海边的沙地，都种着一望无际的碧绿的西瓜。", speaker: null },
  { key: "m3", seq: 3, kind: "character_speech", text: "这不能。须大雪下了才好。我们沙地上，下了雪，我扫出一块空地来，用短棒支起一个大竹匾。", speaker: "闰土" },
  { key: "m4", seq: 4, kind: "narrative", text: "他见我听得出神，又比划了一遍撒下秕谷的样子。", speaker: null },
  { key: "m5", seq: 5, kind: "character_speech", text: "我们日里到海边捡贝壳去，红的绿的都有，鬼见怕也有，观音手也有。", speaker: "闰土" },
];

/** 在途流式行：与持久发言同屏出现，说明「同一角色不会同时留两份」。 */
export const STREAMS: LiveStream[] = [
  {
    streamId: "s-1",
    speaker: "我",
    text: "那你晚上看瓜的时候，真的不怕吗——",
    ended: false,
  },
];

export const INTERACTION: ActiveInteraction = {
  interaction_id: "ix-1",
  mode: "options_with_fallback",
  prompt: "闰土正说到看瓜的夜里，你想怎么接话？",
  options: [
    { option_id: "o1", label: "追问他刺猹那晚的细节", proposed_by: "闰土" },
    { option_id: "o2", label: "说起自己在城里见过的热闹", proposed_by: "母亲" },
  ],
  hint: "选一项，或自己写下要说的话。",
};

/** 续写目标：一条已达成、两条未达成，摆出追踪卡与结局卡的进度。 */
export const STAGE3_GOALS: Stage3Goal[] = [
  { goal_id: 1, description: "让闰土说出一件只有海边孩子才知道的趣事", achieved: true },
  { goal_id: 2, description: "让「我」答应正月过后去海边找闰土", achieved: false },
  { goal_id: 3, description: "在续写中体现两人身份差异带来的隔膜", achieved: false },
];

/** 一条在途命令：画廊用它摆出「正在推进」的顶栏。sentAt 不参与渲染（顶栏不显示秒数）。 */
export const PENDING: PendingCommand = {
  commandId: "cmd-showcase",
  kind: "choose_option",
  label: "选项 追问他刺猹那晚的细节",
  sentAt: 0,
  retries: 0,
  command: {
    schema_version: V,
    command_id: "cmd-showcase",
    session_id: "showcase",
    kind: "choose_option",
    payload: { option_id: "o1" },
    issued_at: null,
  },
};

export const GENERATION_RUNNING: GenerationProgress = {
  schema_version: V,
  status: "running",
  nodes: [
    { node: "collect_materials", status: "succeeded", detail: null },
    { node: "verify_materials", status: "succeeded", detail: null },
    { node: "divide_events", status: "succeeded", detail: "4 个事件" },
    { node: "design_characters", status: "running", detail: "3 / 3" },
    { node: "write_script", status: "pending", detail: null },
    { node: "final_audit", status: "pending", detail: null },
    { node: "design_assets", status: "pending", detail: null },
  ],
  doubter_events: [],
  error: null,
  updated_at: "2026-10-15T11:31:02Z",
};

export const GENERATION_AWAITING: GenerationProgress = {
  schema_version: V,
  status: "awaiting_review",
  nodes: [
    { node: "collect_materials", status: "succeeded", detail: null },
    { node: "verify_materials", status: "succeeded", detail: null },
    { node: "divide_events", status: "succeeded", detail: "4 个事件" },
    { node: "design_characters", status: "succeeded", detail: "3 个角色" },
    { node: "write_script", status: "succeeded", detail: null },
    { node: "final_audit", status: "rejected", detail: "第 2 轮" },
    { node: "design_assets", status: "pending", detail: null },
  ],
  doubter_events: [
    { node: "write_script", verdict: "reject", issues: ["第三场缺少原文依据", "母亲的台词不合时代层"], round: 1 },
    { node: "write_script", verdict: "pass", issues: [], round: 2 },
  ],
  error: null,
  updated_at: "2026-10-15T11:34:40Z",
};

export const GENERATION_FAILED: GenerationProgress = {
  schema_version: V,
  status: "failed",
  nodes: [
    { node: "collect_materials", status: "succeeded", detail: null },
    { node: "verify_materials", status: "failed", detail: null },
    { node: "divide_events", status: "pending", detail: null },
    { node: "design_characters", status: "pending", detail: null },
    { node: "write_script", status: "pending", detail: null },
    { node: "final_audit", status: "pending", detail: null },
    { node: "design_assets", status: "pending", detail: null },
  ],
  doubter_events: [],
  error: "LLM_TIMEOUT：素材考证超时，可重试",
  updated_at: "2026-10-15T11:22:10Z",
};

export const GATE_FINAL: GateReview = {
  schema_version: V,
  gate: "final",
  dossier: null,
  division: null,
  profiles: SCRIPT_PACKAGE.characters,
  package: SCRIPT_PACKAGE,
  evidence: [
    {
      source_type: "web",
      url: "https://example.org/zhoudaoren",
      title: "《故乡》创作背景",
      fetched_at: "2026-10-15T11:28:00Z",
      content_hash: "a1b2c3",
      excerpt: "1919 年作者回故乡绍兴，次年写成这篇小说。",
    },
  ],
};
