"""prompt 代码默认单源（defaults registry）：DB 覆盖层的回退基线。

键为 (stage, node, version) -> {section: text}；各节点模块自带段落常量，\
此处集中注册。新增阶段/节点/版本：在对应模块写 DEFAULTS 并在此登记。
"""

from __future__ import annotations

from app.domain.prompts import (
    character_design,
    collect_materials,
    divide_events,
    doubter,
    write_script,
)

STAGE = "script_gen"

DEFAULTS: dict[tuple[str, str, str], dict[str, str]] = {
    (STAGE, collect_materials.NODE, collect_materials.VERSION): collect_materials.DEFAULTS,
    (STAGE, divide_events.NODE, divide_events.VERSION): divide_events.DEFAULTS,
    (STAGE, character_design.NODE, character_design.VERSION): character_design.DEFAULTS,
    (STAGE, doubter.NODE, doubter.VERSION): doubter.DEFAULTS,
    (STAGE, write_script.NODE, write_script.VERSION): write_script.DEFAULTS,
}

__all__ = ["DEFAULTS", "STAGE"]
