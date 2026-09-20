"""doubter 节点 prompt（issue #28 骨架：素材收集 + 最终总审两处复用）。"""

from __future__ import annotations

PROMPT_VERSION = "doubter.v1"

SYSTEM = (
    "你是剧本生成的 doubter（质疑者）。给定一份生成节点产出的 JSON 产物与其"
    "原文依据，逐条挑出**明显的事实性错误**：与原文人物/事件顺序/关键事实冲突、"
    "编造原文不存在的情节或证据。风格性意见（写得不好看、语言平淡）不属于错误。"
    "没有发现明显错误时判定 pass。只输出一个 JSON 对象，不要 markdown，不要解释。"
)

_OUTPUT_CONTRACT = """\
{
  "verdict": "pass 或 reject",
  "issues": ["逐条错误定位与理由（字符串数组；pass 时为空数组）"]
}"""


def build_user_message(
    *,
    node_name: str,
    artifact_schema_hint: str,
    artifact_json: str,
    source_digest: str,
) -> str:
    """构造 doubter 质询。

    - `node_name`：被质询的节点（如 collect_materials / write_script）。
    - `artifact_schema_hint`：产物字段的简短说明（节点模块自带）。
    - `artifact_json`：产物 JSON。
    - `source_digest`：原文依据摘要（人物/关键事件/素材集结论）。
    """
    return "\n".join(
        [
            f"[prompt_version={PROMPT_VERSION}]",
            SYSTEM,
            "【输出契约（只输出此 JSON）】",
            _OUTPUT_CONTRACT,
            "",
            f"【被质询节点】{node_name}",
            f"【产物字段说明】{artifact_schema_hint}",
            "【产物】",
            artifact_json,
            "",
            "【原文依据摘要（判定事实性错误唯一基准）】",
            source_digest,
        ]
    )
