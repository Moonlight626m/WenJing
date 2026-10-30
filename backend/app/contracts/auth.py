"""账号契约（issue #17 / ADR-0002）：注册/登录请求与对外用户投影。

这些 DTO 是 REST 协议面的一部分，供前端镜像（`frontend/src/lib/contracts/types.ts`）
与 fixtures 使用；实现（哈希/会话）不在此包内。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field, model_validator

from app.contracts.base import VersionedContract
from app.contracts.enums import UserRole


class RegisterRequest(VersionedContract):
    """注册：邮箱或手机号（至少其一）+ 密码 + 昵称。

    角色不在请求内决定：公开注册一律为 `student`，教师账号由 seed / 运营分配。
    """

    # 把「email/phone 至少一个非空」的跨字段规则同步进导出 jsonschema，
    # 否则前端 ajv 校验会放行两个都为 null 的载荷（服务端仍会拒绝）。
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "allOf": [
                {
                    "anyOf": [
                        {"required": ["email"], "properties": {"email": {"type": "string"}}},
                        {"required": ["phone"], "properties": {"phone": {"type": "string"}}},
                    ]
                }
            ]
        },
    )

    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    nickname: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def _require_identifier(self) -> RegisterRequest:
        if not (self.email and self.email.strip()) and not (
            self.phone and self.phone.strip()
        ):
            raise ValueError("email 或 phone 至少提供其一")
        return self


class LoginRequest(VersionedContract):
    """登录：identifier 为注册时的邮箱或手机号。"""

    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserPublic(VersionedContract):
    """当前用户对外投影（绝不包含 password_hash）。"""

    id: uuid.UUID
    org_id: uuid.UUID
    role: UserRole
    email: str | None = None
    phone: str | None = None
    nickname: str
    created_at: datetime | None = None


class AuthSessionInfo(VersionedContract):
    """登录/注册响应：用户 + CSRF token（会话 token 只走 HttpOnly Cookie）。"""

    user: UserPublic
    csrf_token: str


__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "UserPublic",
    "AuthSessionInfo",
]
