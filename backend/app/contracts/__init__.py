"""共享契约包（issue #2）：全 MVP 唯一版本化契约层。

导入面：
- base：ContractModel / VersionedContract / CONTRACTS_SCHEMA_VERSION
- enums：StageValue / InteractionMode / CommandKind / ALLOWED_COMMANDS / EventType / ErrorDomain
- material：MaterialInput / Material / EvidenceRef（Original | Web）
- content：GenreType / GenreClassification / TextAnalysis（人物/关系/场景/关键事件）
- script：ScriptPackage
- commands：PlayerCommand（kind + payload 判别）
- events：DomainEvent / BranchInfo
- runtime：RuntimeState / GameSnapshot / RuntimeUpdate / ActiveInteraction
- errors：ErrorEnvelope / STABLE_CODES
- dto：REST/WS DTO 与显式 mapper

约束：本包不得导入 FastAPI / SQLAlchemy / agents 等实现依赖。
"""

from app.contracts.base import CONTRACTS_SCHEMA_VERSION, ContractModel, VersionedContract

__all__ = [
    "CONTRACTS_SCHEMA_VERSION",
    "ContractModel",
    "VersionedContract",
]
