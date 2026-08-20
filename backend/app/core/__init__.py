# 空 init：避免包级 eager import 造成循环导入。
# 依赖方应直接 from app.core.x import ...。
