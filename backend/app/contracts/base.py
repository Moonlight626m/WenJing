"""共享契约基础：所有契约模型的公共约束。

契约模型是唯一版本化的事实来源（issue #2）：
- 领域模型与 REST/WebSocket DTO 分离，显式 mapper 转换。
- 所有跨模块传输的数据结构在此定义，禁止各模块发明不兼容模型。
- 契约包不得导入 FastAPI / SQLAlchemy / LLM client / agents 等实现依赖。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

CONTRACTS_SCHEMA_VERSION = "1.0.0"


class ContractModel(BaseModel):
    """全部契约模型的基类：禁止额外字段，保证 fixtures 严格校验。"""

    model_config = ConfigDict(extra="forbid")


class VersionedContract(ContractModel):
    """携带契约 schema 版本的契约模型。"""

    schema_version: str = CONTRACTS_SCHEMA_VERSION
