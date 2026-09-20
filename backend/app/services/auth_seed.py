"""默认组织与测试账号 seed（issue #17 / ADR-0002 §6）。

幂等可复跑：按登录标识（email 字段）判断账号是否已存在；存在则跳过。
用法：`cd backend && uv run python -m app.services.auth_seed`
- 标识为无域后缀的演示邮箱（`admin` / `teacher` / `student`），密码默认
  `123456`，可用 `WENJING_SEED_PASSWORD` 覆盖；每次运行都会打印凭据。
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.enums import UserRole
from app.infrastructure.db.session import SessionLocal
from app.services.auth import DEFAULT_ORG_NAME, AuthService

_SEED_ACCOUNTS: tuple[dict[str, str], ...] = (
    {
        "role": UserRole.SUPER_ADMIN.value,
        "email": "admin",
        "nickname": "平台管理员",
    },
    {
        "role": UserRole.TEACHER.value,
        "email": "teacher",
        "nickname": "演示教师",
    },
    {
        "role": UserRole.STUDENT.value,
        "email": "student",
        "nickname": "演示学生",
    },
)


def seed_password() -> str:
    return os.environ.get("WENJING_SEED_PASSWORD", "123456")


async def seed(
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
) -> list[dict[str, str | bool]]:
    """创建默认 org 与三个测试账号；返回每个账号的创建结果。"""
    service = AuthService()
    password = seed_password()
    results: list[dict[str, str | bool]] = []
    async with session_factory() as session:
        await service.default_org(session)
        await session.commit()
        for account in _SEED_ACCOUNTS:
            email = account["email"]
            if await service.find_by_identifier(session, email) is not None:
                results.append({**account, "created": False})
                continue
            await service.create_user(
                session,
                email=email,
                phone=None,
                password=password,
                nickname=account["nickname"],
                role=UserRole(account["role"]),
            )
            await session.commit()
            results.append({**account, "created": True})
    return results


def main() -> None:
    results = asyncio.run(seed())
    print(f"[seed] 默认组织：{DEFAULT_ORG_NAME}")
    password = seed_password()
    for account in results:
        state = "已创建" if account["created"] else "已存在，跳过"
        # 凭据始终打印（含幂等复跑），便于本地/CI 直接登录，无需回查历史输出。
        print(
            f"[seed] {state}  role={account['role']:<11} "
            f"email={account['email']}  password={password}"
        )


if __name__ == "__main__":
    main()
