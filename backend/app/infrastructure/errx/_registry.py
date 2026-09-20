"""错误码注册表：仿 github.com/xh-polaris/psych-post/pkg/errorx 的 register 机制。

所有错误码在 `codes.py` 集中注册，运行期通过 `lookup` 查询定义。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ERROR_MSG = "Service Internal Error"
DEFAULT_IS_AFFECT_STABILITY = True


@dataclass(frozen=True)
class CodeDefinition:
    """单个错误码的定义。"""

    code: int
    message: str
    is_affect_stability: bool = DEFAULT_IS_AFFECT_STABILITY


_REGISTRY: dict[int, CodeDefinition] = {}
_DEFAULT_CODE: int = 1


def register(
    code: int,
    message: str,
    *,
    is_affect_stability: bool = DEFAULT_IS_AFFECT_STABILITY,
) -> None:
    """注册或覆盖一个错误码定义。"""
    global _REGISTRY
    _REGISTRY[code] = CodeDefinition(
        code=code, message=message, is_affect_stability=is_affect_stability
    )


def lookup(code: int) -> CodeDefinition:
    """查询错误码定义；未注册的回落为默认定义。"""
    return _REGISTRY.get(code, CodeDefinition(code, DEFAULT_ERROR_MSG))


def set_default_error_code(code: int) -> None:
    global _DEFAULT_CODE
    _DEFAULT_CODE = code


def default_error_code() -> int:
    return _DEFAULT_CODE


def all_definitions() -> dict[int, CodeDefinition]:
    return dict(_REGISTRY)
