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

/** 生成管线的四个阶段名（backend _GENERATION_PHASES 对应）。 */
export const GENERATION_PHASES = ["genre", "research", "generate", "verify"] as const;

export const PHASE_LABELS: Record<string, string> = {
  genre: "体裁判断",
  research: "网络研究",
  generate: "剧本生成",
  verify: "校验",
};
