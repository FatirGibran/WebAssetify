"""Tests for URL security and SSRF protection module."""

from unittest.mock import patch
import socket

from parsers.security import is_safe_url


def test_is_safe_url_blocks_unsafe_schemes():
    assert is_safe_url("ftp://example.com/file.png") is False
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("javascript:alert(1)") is False
    assert is_safe_url("") is False


def test_is_safe_url_blocks_blocked_hostnames():
    assert is_safe_url("http://localhost:8080/image.jpg") is False
    assert is_safe_url("http://sub.localhost/image.jpg") is False
    assert is_safe_url("http://metadata.google.internal/computeMetadata/v1") is False


def test_is_safe_url_blocks_cloud_metadata_ips():
    assert is_safe_url("http://169.254.169.254/latest/meta-data") is False
    assert is_safe_url("http://100.100.100.200/latest/meta-data") is False


def test_is_safe_url_blocks_private_and_loopback_ips():
    assert is_safe_url("http://127.0.0.1/status") is False
    assert is_safe_url("http://10.0.0.5/admin") is False
    assert is_safe_url("http://192.168.1.1/secret") is False
    assert is_safe_url("http://172.16.0.1/internal") is False


@patch("socket.getaddrinfo")
def test_is_safe_url_allows_public_ips(mock_getaddrinfo):
    # Mock DNS resolution for example.com to public IP (e.g. 93.184.216.34)
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))
    ]
    assert is_safe_url("https://example.com/assets/banner.png") is True


@patch("socket.getaddrinfo")
def test_is_safe_url_blocks_dns_rebinding_to_private_ip(mock_getaddrinfo):
    # If a public domain resolves to a private IP (DNS rebinding attack)
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.100", 0))
    ]
    assert is_safe_url("https://malicious-domain-rebinding.com/evil") is False
