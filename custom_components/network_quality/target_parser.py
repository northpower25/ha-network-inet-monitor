"""Target parsing helpers for host/port extraction and validation."""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

_HOSTNAME_RE = re.compile(
    r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$"
)


def parse_target_host_port(target: str) -> tuple[str, int | None] | None:
    """Parse configured target to `(host, port)` supporting IPv6 and URLs."""
    candidate = target.strip()
    if not candidate:
        return None

    parsed = urlparse(candidate)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        try:
            host = parsed.hostname
            port = parsed.port
        except ValueError:
            return None
        if not host:
            return None
        return (host.strip("[]").strip(), port)

    head = candidate.split("/", 1)[0].strip()
    if not head:
        return None

    host: str
    port: int | None = None

    if head.startswith("["):
        closing = head.find("]")
        if closing <= 1:
            return None
        host = head[1:closing]
        remainder = head[closing + 1 :]
        if remainder:
            if not remainder.startswith(":"):
                return None
            port_text = remainder[1:]
            if not port_text.isdigit():
                return None
            port = int(port_text)
    elif ":" not in head:
        host = head
    elif head.count(":") == 1:
        host, port_text = head.rsplit(":", 1)
        if not host or not port_text.isdigit():
            return None
        port = int(port_text)
    else:
        try:
            ipaddress.IPv6Address(head)
            host = head
        except ValueError:
            maybe_host, maybe_port = head.rsplit(":", 1)
            if not maybe_port.isdigit():
                return None
            try:
                ipaddress.IPv6Address(maybe_host)
            except ValueError:
                return None
            host = maybe_host
            port = int(maybe_port)

    if not host:
        return None
    if port is not None and not (0 < port < 65536):
        return None
    return (host.strip("[]").strip(), port)


def _is_valid_host(host: str) -> bool:
    """Return whether host is valid IPv4/IPv6/hostname."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if "%" in host:
        base, _, zone = host.partition("%")
        if zone:
            try:
                ipaddress.IPv6Address(base)
                return True
            except ValueError:
                pass
    return bool(_HOSTNAME_RE.match(host))


def is_valid_target(target: str) -> bool:
    """Return True for valid IP/hostname/URL/host:port targets."""
    parsed = parse_target_host_port(target)
    if parsed is None:
        return False
    host, _ = parsed
    return _is_valid_host(host)
