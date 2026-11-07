"""prompt 覆盖层 seed（PromptMgr 组件）：从代码 defaults 幂等写入 prompts 表。

`make seed` 入口（app.services.auth_seed）调用；已存在且未禁用的行跳过，\
保持 DB 覆盖不被重置。DB 无表/不可用时静默降级（seed 不能因 prompt 表失败）。
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.prompts.defaults import DEFAULTS
from app.infrastructure.models.prompt import PromptTemplate

logger = logging.getLogger("wenjing.seed.prompts")

DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("collect_materials", "system"): "角色定位与使命（system prompt 主体）",
    ("collect_materials", "evidence_policy"): "可信度协议（来源×可信度、claims/conflicts 登记）",
    ("collect_materials", "structure_rules"): "背景/时代/情节的结构维度（知人论世）",
    ("collect_materials", "persona_rules"): "应试式人物形象分析维度",
    ("collect_materials", "checklist"): "素材收集输出前自检清单",
    ("divide_events", "system"): "角色定位与忠实性总纲",
    ("divide_events", "scene_rules"): "场景划分判据（价值转折/切换点）",
    ("divide_events", "beat_rules"): "节拍粒度判据（行为/反应交换）",
    ("divide_events", "interaction_rules"): "玩家介入点写法",
    ("divide_events", "visual_rules"): "场景视觉锚点（visual_notes，只写原文可推断）",
    ("divide_events", "branch_rules"): "伪分支规格（挂在介入点上的替代过场）",
    ("divide_events", "option_rules"): "珊瑚图决策点（选项目标与 canonical 主线）",
    ("divide_events", "ending_rules"): "珊瑚图结局表（canonical/alternate/distractor）",
    ("divide_events", "checklist"): "事件划分输出前自检清单",
    ("character_design", "system"): "角色定位与忠实性总纲",
    ("character_design", "trait_rules"): "性格标签「标签+证据+行为化」写作法",
    ("character_design", "speech_rules"): "说话风格五要素与示例台词",
    ("character_design", "boundary_rules"): "知识边界与禁编造约束",
    ("character_design", "playability_rules"): "is_player_playable 判断准则",
    ("character_design", "appearance_rules"): "外貌五要素（文生图锚定，原文可推断）",
    ("character_design", "checklist"): "人物设定输出前自检清单",
    ("doubter", "system"): "角色定位（严苛但只对事实负责的质疑者）",
    ("doubter", "procedure"): "doubter 四步审核流程（拆解→取证→判定→汇总）",
    ("doubter", "baseline"): "doubter 事实基准唯一性条款",
    ("doubter", "negative_list"): "doubter 负面清单（禁风格意见）",
    ("doubter", "branch_audit_rules"): "doubter 伪分支与视觉锚点的忠实性审核",
    ("doubter", "checklist"): "doubter 输出前自检清单",
    ("write_script", "role"): "编剧教学场景定位与红线",
    ("write_script", "dialogue_rules"): "对白写作准则",
    ("write_script", "scene_rules"): "场景开场四要素与舞台指示写法",
    ("write_script", "beat_rules"): "beat 留白与戏剧目标",
    ("write_script", "branch_rules"): "伪分支补写判据（分支第二遍调用使用）",
    ("write_script", "checklist"): "剧本书写输出前自检清单",
    ("write_dialogue", "system"): "台词作者定位（不改写节拍、不新增情节）",
    ("write_dialogue", "dialogue_rules"): "台词粒度与信息增量判据",
    ("write_dialogue", "speaker_rules"): "说话人约束（participants 内、旁白用 null）",
    ("write_dialogue", "branch_rules"): "分支台词边界（不改写关键事件与结局）",
    ("write_dialogue", "checklist"): "台词预写输出前自检清单",
}


def _description(node: str, section: str) -> str:
    return DESCRIPTIONS.get((node, section), f"{node}.{section}")


async def seed_prompts(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """幂等写入 prompt 覆盖行，返回新建行数。"""
    created = 0
    async with session_factory() as session:
        for (stage, node, version), sections in DEFAULTS.items():
            for section, body in sections.items():
                exists = (
                    await session.execute(
                        select(PromptTemplate.id).where(
                            PromptTemplate.stage == stage,
                            PromptTemplate.node == node,
                            PromptTemplate.version == version,
                            PromptTemplate.section == section,
                        )
                    )
                ).first()
                if exists is not None:
                    continue
                stmt = (
                    pg_insert(PromptTemplate)
                    .values(
                        stage=stage,
                        node=node,
                        version=version,
                        section=section,
                        body=body,
                        description=_description(node, section),
                        enabled=True,
                    )
                    .on_conflict_do_nothing(
                        index_elements=["stage", "node", "version", "section"]
                    )
                )
                await session.execute(stmt)
                created += 1
        await session.commit()
    logger.info("prompt_seed_done created=%d", created)
    return created
