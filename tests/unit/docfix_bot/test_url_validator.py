"""Tests for docfix_bot.url_validator (SSRF protection).

Covers LLD #2 test scenarios T190-T220.
"""

from __future__ import annotations

from unittest.mock import patch

from docfix_bot.url_validator import is_private_ip, validate_ip_safety


class TestIsPrivateIp:
    """Tests for is_private_ip."""

    def test_loopback_v4(self) -> None:
        assert is_private_ip("127.0.0.1") is True

    def test_loopback_v4_other(self) -> None:
        assert is_private_ip("127.0.0.2") is True

    def test_private_10(self) -> None:
        assert is_private_ip("10.0.0.1") is True

    def test_private_172(self) -> None:
        assert is_private_ip("172.16.0.1") is True

    def test_private_192(self) -> None:
        assert is_private_ip("192.168.1.1") is True

    def test_link_local(self) -> None:
        assert is_private_ip("169.254.169.254") is True  # AWS metadata

    def test_ipv6_loopback(self) -> None:
        assert is_private_ip("::1") is True

    def test_ipv6_private(self) -> None:
        assert is_private_ip("fc00::1") is True

    def test_public_ip(self) -> None:
        assert is_private_ip("8.8.8.8") is False

    def test_public_ip_2(self) -> None:
        assert is_private_ip("93.184.216.34") is False

    def test_invalid_ip(self) -> None:
        assert is_private_ip("not-an-ip") is True  # Invalid treated as unsafe


class TestValidateIpSafety:
    """Tests for validate_ip_safety (SSRF validation)."""

    @patch("docfix_bot.url_validator.socket.getaddrinfo")
    def test_public_ip_allowed(self, mock_dns: object) -> None:
        mock_dns.return_value = [  # type: ignore[attr-defined]
            (2, 1, 6, "", ("93.184.216.34", 443)),
        ]
        result = validate_ip_safety("https://example.com/page")
        assert result["is_safe"] is True
        assert result["resolved_ip"] == "93.184.216.34"

    @patch("docfix_bot.url_validator.socket.getaddrinfo")
    def test_localhost_blocked(self, mock_dns: object) -> None:
        mock_dns.return_value = [  # type: ignore[attr-defined]
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ]
        result = validate_ip_safety("http://localhost/secret")
        assert result["is_safe"] is False
        assert "Private IP" in result["rejection_reason"]

    @patch("docfix_bot.url_validator.socket.getaddrinfo")
    def test_aws_metadata_blocked(self, mock_dns: object) -> None:
        mock_dns.return_value = [  # type: ignore[attr-defined]
            (2, 1, 6, "", ("169.254.169.254", 443)),
        ]
        result = validate_ip_safety("http://169.254.169.254/latest/meta-data")
        assert result["is_safe"] is False

    @patch("docfix_bot.url_validator.socket.getaddrinfo")
    def test_private_10_blocked(self, mock_dns: object) -> None:
        mock_dns.return_value = [  # type: ignore[attr-defined]
            (2, 1, 6, "", ("10.0.0.5", 443)),
        ]
        result = validate_ip_safety("http://internal-server/api")
        assert result["is_safe"] is False

    @patch("docfix_bot.url_validator.socket.getaddrinfo")
    def test_dns_failure(self, mock_dns: object) -> None:
        import socket
        mock_dns.side_effect = socket.gaierror("Name resolution failed")  # type: ignore[attr-defined]
        result = validate_ip_safety("https://nonexistent.invalid")
        assert result["is_safe"] is False
        assert "DNS resolution failed" in result["rejection_reason"]

    def test_no_hostname(self) -> None:
        result = validate_ip_safety("not-a-url")
        assert result["is_safe"] is False
        assert "No hostname" in result["rejection_reason"]

    @patch("docfix_bot.url_validator.socket.getaddrinfo")
    def test_multiple_ips_one_private(self, mock_dns: object) -> None:
        mock_dns.return_value = [  # type: ignore[attr-defined]
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("10.0.0.1", 443)),
        ]
        result = validate_ip_safety("https://mixed.example.com")
        assert result["is_safe"] is False  # Any private IP blocks
