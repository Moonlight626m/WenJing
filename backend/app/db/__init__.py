"""db 包（各模块见下；`__init__` 保持精简避免循环导入）。

- `session`：引擎与会话工厂。
- `models`：ORM 模型（`app/models`）。
- `event_store`：持久化事件存储。
- `factory`：引擎接持久化工厂（建库只走 Alembic 迁移）。
"""
