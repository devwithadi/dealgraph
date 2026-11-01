import ipaddress
import socket
from typing import Callable, Collection
from urllib.parse import urlsplit

from app.core.errors import AppError


class PublicUrlError(AppError, ValueError):
    pass


def resolve_host(host: str) -> list[str]:
    return list({item[4][0] for item in socket.getaddrinfo(host, None)})


def validate_public_url(
    url: str,
    *,
    schemes: Collection[str],
    ports: Collection[int],
    blocked_hosts: Collection[str] = (),
    resolver: Callable[[str], list[str]] = resolve_host,
    allow_local: bool = False,
) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in schemes or not parsed.hostname:
        raise PublicUrlError(f"Unsupported URL: {url}")
    if parsed.username or parsed.password:
        raise PublicUrlError("Credentials in URLs are forbidden")
    try:
        port = parsed.port
    except ValueError as error:
        raise PublicUrlError("Invalid port") from error
    default_port = 443 if parsed.scheme == "https" else 80
    if (port or default_port) not in ports:
        raise PublicUrlError(f"Only ports {', '.join(map(str, sorted(ports)))} are allowed")
    host = parsed.hostname.rstrip(".").lower()
    if any(host == blocked or host.endswith(f".{blocked}") for blocked in blocked_hosts):
        raise PublicUrlError(f"Source is blocked by policy: {host}")
    try:
        ipaddress.ip_address(host)
        addresses = [host]
    except ValueError:
        addresses = resolver(host)
    if not addresses:
        raise PublicUrlError(f"Host did not resolve: {host}")
    for address in addresses:
        ip_obj = ipaddress.ip_address(address)
        if allow_local and (ip_obj.is_loopback or host == "localhost"):
            continue
        if not ip_obj.is_global:
            raise PublicUrlError(f"Non-public target rejected: {address}")
    return url
