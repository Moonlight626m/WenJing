"""资源访问策略（issue #18 / ADR-0002 §3、§6）。

- `Actor`：一次请求的领域身份（user/org/role），由 `Principal`（HTTP 层）投影而来，
  使应用层（`SessionApplication`）在不依赖 FastAPI/Cookie 的前提下做鉴权。
- 会话（剧情世界）仅 owner 可见可玩：非 owner（含同 org 的其他人）一律
  `AUTH_FORBIDDEN`（403）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.contracts.enums import UserRole
from app.errx import codes, new


@dataclass(frozen=True)
class Actor:
    """领域身份：谁在操作（不含密码/会话 token 等凭证细节）。"""

    user_id: uuid.UUID
    org_id: uuid.UUID
    role: UserRole


def require_session_access(actor: Actor, session: object) -> None:
    """校验 actor 是否可访问该会话；非 owner 抛 403。

    `session` 仅需具备 `owner_user_id`（避免 access 模块耦合 ORM 模型）。
    """
    if getattr(session, "owner_user_id", None) != actor.user_id:
        raise new(codes.AUTH_FORBIDDEN, extra={"reason": "not session owner"})


__all__ = ["Actor", "require_session_access"]
