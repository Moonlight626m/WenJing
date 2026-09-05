"""进程内指标注册表（issue #3 /metrics）。

MVP 用轻量文本格式（Prometheus exposition 兼容子集），后续可接 collector。
覆盖 spec 要求：请求/错误数、生成成功率、LLM 时延与 token、搜索时延、
WS 连接数、command 时延、DB 事务失败。
"""

from __future__ import annotations

import threading


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}

    def inc(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + value

    def dec(self, name: str, value: float = 1.0) -> None:
        self.inc(name, -value)

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def get(self, name: str) -> float:
        with self._lock:
            if name in self._counters:
                return self._counters[name]
            return self._gauges.get(name, 0.0)

    def render(self) -> str:
        """Prometheus 文本协议（简化版）。"""
        lines = []
        with self._lock:
            for name in sorted(self._counters):
                kind = "counter"
                help_text = _HELP.get(name, "")
                if help_text:
                    lines.append(f"# HELP {name} {help_text}")
                    lines.append(f"# TYPE {name} {kind}")
                lines.append(f"{name} {self._counters[name]}")
            for name in sorted(self._gauges):
                kind = "gauge"
                help_text = _HELP.get(name, "")
                if help_text:
                    lines.append(f"# HELP {name} {help_text}")
                    lines.append(f"# TYPE {name} {kind}")
                lines.append(f"{name} {self._gauges[name]}")
        return "\n".join(lines) + "\n"


_HELP = {
    "wenjing_requests_total": "Total HTTP requests",
    "wenjing_errors_total": "Total error envelopes produced",
    "wenjing_ws_connections": "Active WebSocket connections",
    "wenjing_commands_total": "Player commands processed",
    "wenjing_db_tx_failures_total": "Failed DB transactions",
    "wenjing_generation_successes_total": "Successful script generations",
    "wenjing_generation_failures_total": "Failed script generations",
}


def observe_latency(metrics: Metrics, base_name: str, seconds: float) -> None:
    """以累计直方图语义记录时延（sum + count 两计数器）。"""
    metrics.inc(f"{base_name}_seconds_sum", seconds)
    metrics.inc(f"{base_name}_seconds_count")


metrics = Metrics()
