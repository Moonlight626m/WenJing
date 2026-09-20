import type {
  ScriptStatus,
  ScriptVisibility,
  UsagePurpose,
} from "@/lib/contracts/types";

export const STAGE_LABELS: Record<string, string> = {
  init: "待导入",
  stage1_creating: "生成中",
  stage1_complete: "剧本就绪",
  stage2_reenacting: "剧情还原",
  stage2_complete: "还原完成",
  stage3_extending: "剧情续写",
  ended: "已结束",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage;
}

export const GENRE_LABELS: Record<string, string> = {
  novel: "小说",
  narrative: "叙事文",
  drama: "戏剧",
  character_story: "人物故事",
  expository: "说明文",
  argumentative: "议论文",
  scenery: "写景",
  poetry: "诗歌",
  unknown: "未知体裁",
};

export function genreLabel(genre: string): string {
  return GENRE_LABELS[genre] ?? genre;
}

/** 生成 workflow 的节点名（backend/app/contracts/generation.py GenerationNode）。 */
export const GENERATION_NODE_LABELS: Record<string, string> = {
  collect_materials: "素材收集",
  verify_materials: "素材考证",
  divide_events: "事件划分",
  design_characters: "人物设定",
  write_script: "剧本书写",
  final_audit: "总审",
};

/** 生成节点名别名（详情页进度条使用）。 */

/** 剧本生命周期状态（backend/app/contracts/enums.py ScriptStatus）。 */
export const SCRIPT_STATUS_LABELS: Record<ScriptStatus, string> = {
  draft: "草稿",
  published: "已发布",
  unpublished: "已下架",
};

export function scriptStatusLabel(status: ScriptStatus): string {
  return SCRIPT_STATUS_LABELS[status] ?? status;
}

/** 剧本可见性（backend/app/contracts/enums.py ScriptVisibility）。 */
export const SCRIPT_VISIBILITY_LABELS: Record<ScriptVisibility, string> = {
  org: "本校可见",
  public: "公开",
};

export function scriptVisibilityLabel(visibility: ScriptVisibility): string {
  return SCRIPT_VISIBILITY_LABELS[visibility] ?? visibility;
}

/** LLM 调用用途（backend/app/contracts/enums.py UsagePurpose，issue #22/#28）。 */
export const USAGE_PURPOSE_LABELS: Record<UsagePurpose, string> = {
  stage1: "剧本生成",
  agent: "角色 Agent",
  verify: "校验",
  collect_materials: "素材收集",
  doubter: "考证质询",
  divide_events: "事件划分",
  character_design: "人物设定",
  script_writing: "剧本书写",
};

export function usagePurposeLabel(purpose: UsagePurpose): string {
  return USAGE_PURPOSE_LABELS[purpose] ?? purpose;
}
