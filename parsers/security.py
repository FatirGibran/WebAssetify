"""URL security and SSRF protection module for WebAssetify.

Prevents Server-Side Request Forgery (SSRF) attacks by verifying that candidate URLs
resolve exclusively to public, routable IP addresses. Blocks loopback, private networks
(RFC 1918), link-local addresses, and cloud provider metadata endpoints (e.g. 169.254.169.254).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Cloud provider metadata IP strings and dangerous patterns
DANGEROUS_IPS = {
    "169.254.169.254",  # AWS, GCP, Azure, OpenStack instance metadata
    "fd00:ec2::254",    # AWS IPv6 metadata
    "100.100.100.200",  # Alibaba Cloud metadata
}

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "instance-data",
}


def is_safe_url(url: str) -> bool:
    """Validate that a URL is safe to fetch and does not point to internal/metadata endpoints.

    Args:
        url: The web URL to inspect.

    Returns:
        True if the URL uses http(s) and resolves only to public IPs; False otherwise.
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    # 1. Scheme enforcement: only http and https are permitted
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        logger.warning("SSRF Guard: blocked unsafe scheme '%s' in %s", scheme, url)
        return False

    hostname = parsed.hostname
    if not hostname:
        logger.warning("SSRF Guard: no hostname found in %s", url)
        return False

    hostname = hostname.lower()

    # 2. Block known internal hostnames
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".localhost") or hostname.endswith(".local") or hostname.endswith(".internal"):
        logger.warning("SSRF Guard: blocked internal hostname '%s' in %s", hostname, url)
        return False

    # 3. Direct IP address check or DNS resolution
    try:
        # Resolve hostname to IP addresses (supports both IPv4 and IPv6)
        addr_info = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        logger.warning("SSRF Guard: DNS resolution failed for hostname '%s': %s", hostname, e)
        return False
    except Exception as e:
        logger.warning("SSRF Guard: resolution error for %s: %s", hostname, e)
        return False

    if not addr_info:
        return False

    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]

        # Check explicit blacklisted metadata IPs
        if ip_str in DANGEROUS_IPS:
            logger.warning("SSRF Guard: blocked cloud metadata IP '%s' for %s", ip_str, url)
            return False

        try:
            ip = ipaddress.ip_address(ip_str)

            # Block private, loopback, link-local, reserved, or multicast addresses
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                logger.warning("SSRF Guard: blocked private/non-routable IP '%s' for %s", ip_str, url)
                return False

        except ValueError:
            logger.warning("SSRF Guard: invalid IP '%s' encountered", ip_str)
            return False

    return True
