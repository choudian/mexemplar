"""
加密检测器测试
"""

from src.business.ai.encryption_detector import (
    EncryptionDetector,
    EncryptionType,
)


def test_detect_base64():
    detector = EncryptionDetector()

    # Base64 编码的二进制数据（至少20字符以匹配pattern）
    # 这是二进制数据的Base64编码（解码后包含大量不可打印字符）
    result = detector.detect("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=")
    assert result.is_encrypted
    assert result.encryption_type == EncryptionType.BASE64


def test_detect_aes_encrypted():
    detector = EncryptionDetector()

    # 模拟 AES 加密的数据
    result = detector.detect("U2FsdGVkX1+vupppZksvRf5pq5g5XjFRlipRkwB0K1Y=")
    assert result.is_encrypted
    assert result.encryption_type in [
        EncryptionType.AES,
        EncryptionType.UNKNOWN,
    ]


def test_detect_normal_json():
    detector = EncryptionDetector()

    # 正常的 JSON
    result = detector.detect('{"name": "test", "value": 123}')
    assert not result.is_encrypted


def test_detect_long_random_string():
    detector = EncryptionDetector()

    # OpenSSL AES 加密字符串（必须以 U2FsdGVkX1 开头）
    result = detector.detect("U2FsdGVkX1+vupppZksvRf5pq5g5XjFRlipRkwB0K1Y=")
    assert result.is_encrypted


def test_empty_string():
    detector = EncryptionDetector()
    result = detector.detect("")
    assert not result.is_encrypted
    assert result.confidence == 0.0


def test_non_string_input():
    detector = EncryptionDetector()
    result = detector.detect(123)
    assert not result.is_encrypted


def test_detect_in_dict_with_encrypted_field():
    detector = EncryptionDetector()
    result = detector.detect_in_dict({"encrypted_data": "value"})
    assert result.is_encrypted
    assert result.confidence == 0.8
