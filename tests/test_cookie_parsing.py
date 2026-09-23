"""Tests for cookie expiry parsing logic."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from xueqiu_monitor import _get_token_expiry, _jwt_expiry


class TestCookieParsing:
    """Test suite for cookie expiry detection."""

    def test_xq_a_token_with_timestamp(self):
        """xq_a_token 尾部时间戳应该被正确解析（毫秒格式）"""
        # 2026-01-01 00:00:00 的毫秒时间戳
        cookie = "xq_a_token=abc123_1735660800000; u=1234567890"
        expiry = _get_token_expiry(cookie)
        assert expiry == 1735660800.0

    def test_xq_a_token_with_timestamp_seconds(self):
        """xq_a_token 尾部时间戳应该被正确解析（秒格式）"""
        cookie = "xq_a_token=abc123_1735660800; u=1234567890"
        expiry = _get_token_expiry(cookie)
        assert expiry == 1735660800.0

    def test_xq_a_token_without_timestamp(self):
        """没有时间戳的 xq_a_token 应该返回 None"""
        cookie = "xq_a_token=abc123; u=1234567890"
        expiry = _get_token_expiry(cookie)
        assert expiry is None

    def test_xq_a_token_invalid_timestamp(self):
        """无效时间戳应该返回 None"""
        cookie = "xq_a_token=abc123_invalid; u=1234567890"
        expiry = _get_token_expiry(cookie)
        assert expiry is None

    def test_xq_a_token_out_of_range_timestamp(self):
        """超出合理范围的时间戳应该返回 None"""
        # 1970 年的时间戳
        cookie = "xq_a_token=abc123_100000; u=1234567890"
        expiry = _get_token_expiry(cookie)
        assert expiry is None

    def test_jwt_expiry_valid(self):
        """有效的 JWT 应该正确解析 exp 字段"""
        # 构造一个简单的 JWT（未签名，但有有效的 payload）
        # payload: {"exp": 1735660800}
        # Base64: eyJleHAiOiAxNzM1NjYwODAwfQ==
        token = "header.eyJleHAiOiAxNzM1NjYwODAwfQ.signature"
        expiry = _jwt_expiry(token)
        assert expiry == 1735660800.0

    def test_jwt_expiry_no_exp_field(self):
        """没有 exp 字段的 JWT 应该返回 None"""
        # payload: {"sub": "user123"}
        # Base64: eyJzdWIiOiAidXNlcjEyMyJ9
        token = "header.eyJzdWIiOiAidXNlcjEyMyJ9.signature"
        expiry = _jwt_expiry(token)
        assert expiry is None

    def test_jwt_expiry_invalid_format(self):
        """格式错误的 JWT 应该返回 None"""
        token = "not-a-valid-jwt"
        expiry = _jwt_expiry(token)
        assert expiry is None

    def test_jwt_expiry_invalid_base64(self):
        """Base64 解码失败应该返回 None"""
        token = "header.invalid-base64!!!.signature"
        expiry = _jwt_expiry(token)
        assert expiry is None

    def test_xq_id_token_priority(self):
        """xq_id_token 的 JWT exp 应该优先于 xq_a_token 时间戳"""
        # JWT with exp: 1735660800 (2026-01-01)
        jwt_token = "header.eyJleHAiOiAxNzM1NjYwODAwfQ.signature"
        # xq_a_token with different timestamp (2026-06-01)
        cookie = f"xq_id_token={jwt_token}; xq_a_token=abc123_1748736000000; u=1234567890"
        expiry = _get_token_expiry(cookie)
        # 应该使用 JWT 的 exp (2026-01-01)
        assert expiry == 1735660800.0

    def test_cookie_with_quotes(self):
        """带引号的 cookie 值应该被正确处理"""
        cookie = 'xq_a_token="abc123_1735660800000"; u="1234567890"'
        expiry = _get_token_expiry(cookie)
        assert expiry == 1735660800.0

    def test_cookie_with_extra_fields(self):
        """包含其他字段的 cookie 应该正常解析"""
        cookie = "session=xyz; xq_a_token=abc123_1735660800000; u=1234567890; path=/; secure"
        expiry = _get_token_expiry(cookie)
        assert expiry == 1735660800.0

    def test_missing_xq_a_token(self):
        """缺少 xq_a_token 的 cookie 应该返回 None"""
        cookie = "u=1234567890; session=xyz"
        expiry = _get_token_expiry(cookie)
        assert expiry is None

    def test_empty_cookie(self):
        """空 cookie 应该返回 None"""
        expiry = _get_token_expiry("")
        assert expiry is None

    def test_jwt_exp_too_small(self):
        """exp 值太小（不像时间戳）应该返回 None"""
        # payload: {"exp": 12345}
        # Base64: eyJleHAiOiAxMjM0NX0=
        token = "header.eyJleHAiOiAxMjM0NX0.signature"
        expiry = _jwt_expiry(token)
        assert expiry is None
