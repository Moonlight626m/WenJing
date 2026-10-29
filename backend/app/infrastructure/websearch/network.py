"""SSRF / DNS 安全校验（issue #10 验收标准 2）。

- 仅允许 http/https scheme。
- 解析 host 后拒绝 loopback / private / link-local / metadata 地址。
- 每次重定向跳转都重新执行完整校验（由 safe_fetcher 调用）。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),        # "this" network（含 0.0.0.0）
    ipaddress.ip_network("10.0.0.0/8"),       # private
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),      # loopback
    ipaddress.ip_network("169.254.0.0/16"),   # link-local（含 metadata 169.254.169.254）
    ipaddress.ip_network("172.16.0.0/12"),    # private
    ipaddress.ip_network("192.168.0.0/16"),   # private
    ipaddress.ip_network("198.18.0.0/15"),    # benchmark
    ipaddress.ip_network("224.0.0.0/4"),      # multicast
    ipaddress.ip_network("240.0.0.0/4"),      # reserved
    ipaddress.ip_network("::1/128"),          # loopback v6
    ipaddress.ip_network("::/128"),           # unspecified
    ipaddress.ip_network("fc00::/7"),         # unique-local v6
    ipaddress.ip_network("fe80::/10"),        # link-local v6
    ipaddress.ip_network("ff00::/8"),         # multicast v6
)


def validate_url_scheme(url: str) -> str:
    """校验 scheme 为 http/https，返回小写 scheme。"""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"scheme not allowed: {parsed.scheme or '(none)'}")
    if not parsed.hostname:
        raise ValueError("url has no host")
    return parsed.scheme.lower()


def is_blocked_ip(ip: str) -> bool:
    """单个 IP 是否命中封禁网段。"""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # 无法解析的地址一律拒绝
    return any(addr in net for net in BLOCKED_NETWORKS)


def resolve_and_validate(host: str, port: int) -> list[str]:
    """解析 host 并返回全部非封禁 IP；存在封禁 IP 或解析失败则拒绝。

    IPv4/IPv6 双栈解析，任一条命中封禁网段即整体拒绝（宁拒勿漏）。
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips: list[str] = []
    for _family, _socktype, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        if is_blocked_ip(ip):
            raise ValueError(f"resolved to blocked address: {ip}")
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise ValueError("no address resolved")
    return ips


def validate_target(url: str) -> None:
    """对目标 URL 做完整 SSRF/DNS 校验；失败抛 ValueError（由上层包装为 errx）。"""
    scheme = validate_url_scheme(url)
    parsed = urlparse(url)
    port = parsed.port or (443 if scheme == "https" else 80)
    resolve_and_validate(parsed.hostname or "", port)
