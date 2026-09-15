"""账号与鉴权（issue #17 / ADR-0002）。

- `passwords`：argon2-cffi 密码哈希
- `service`：注册 / 登录 / 登出 / 会话解析（滑过期）与 CSRF token
- `deps`：FastAPI 依赖（当前用户 + CSRF 校验）
- `seed`：默认组织与测试账号，幂等可复跑
"""
