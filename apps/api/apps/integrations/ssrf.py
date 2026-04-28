import ipaddress
import socket
from urllib.parse import urlparse

from django.core.exceptions import ValidationError

UNSAFE_HOSTNAMES = {"localhost", "localhost.localdomain"}
METADATA_IPS = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
}


def validate_outbound_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValidationError("Integration URL must use HTTPS.")
    if not parsed.hostname:
        raise ValidationError("Integration URL must include a hostname.")
    if parsed.username or parsed.password:
        raise ValidationError("Integration URL must not include user info.")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in UNSAFE_HOSTNAMES or hostname.endswith(".localhost"):
        raise ValidationError("Integration URL must not target localhost.")

    addresses = _resolve_host_addresses(hostname)
    for address in addresses:
        _validate_public_address(address)

    return url


def _resolve_host_addresses(
    hostname: str,
) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        return {literal_ip}

    try:
        results = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValidationError("Integration URL hostname could not be resolved.") from exc

    addresses = set()
    for result in results:
        sockaddr = result[4]
        addresses.add(ipaddress.ip_address(sockaddr[0]))
    return addresses


def _validate_public_address(address) -> None:
    if address in METADATA_IPS:
        raise ValidationError("Integration URL must not target metadata services.")
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ValidationError("Integration URL must resolve to a public address.")
