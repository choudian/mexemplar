# ⚠️ TODO: 此模块尚未集成到工作流中
# 加密检测器 - 识别网络请求响应中的加密数据
# 计划在后续版本中集成到数据预处理流程

"""
加密检测器

识别网络请求响应中的加密数据
"""

import re
import base64
from dataclasses import dataclass
from typing import Optional
from enum import Enum

from src.data.unified_config import get_unified_config


class EncryptionType(str, Enum):
    """加密类型"""

    BASE64 = "base64"
    AES = "aes"
    UNKNOWN = "unknown"


@dataclass
class EncryptionDetectionResult:
    """加密检测结果"""

    is_encrypted: bool
    encryption_type: Optional[EncryptionType]
    confidence: float  # 0.0 - 1.0
    reason: str


class EncryptionDetector:
    """加密检测器"""

    # Confidence thresholds
    CONFIDENCE_HIGH = 0.95
    CONFIDENCE_BASE64_BINARY = 0.9
    CONFIDENCE_ENCRYPTED_FIELD = 0.8
    CONFIDENCE_RANDOM_STRING = 0.7
    CONFIDENCE_LONG_HEX = 0.6

    # 加密特征模式
    PATTERNS = {
        "open_ssl_aes": re.compile(r"^U2FsdGVkX1"),  # OpenSSL AES 加密
        "base64": re.compile(r"^[A-Za-z0-9+/=]{20,}=?$"),  # Base64 编码（最小20字符）
        "hex_long": re.compile(r"^[0-9a-fA-F]{64,}$"),  # 长十六进制
    }

    def __init__(self):
        """初始化加密检测器并加载配置"""
        config = get_unified_config()

        # 从配置中读取阈值，使用默认值作为fallback
        self.MIN_BASE64_LENGTH = config.get(
            'recording.encryption_detection.base64_min_length',
            default=20
        )
        self.MIN_RANDOM_STRING_LENGTH = 50
        self.MIN_UNIQUE_CHARS_FOR_ENTROPY = 40
        # 🔧 从配置读取二进制数据可打印字符比例阈值（替换硬编码的 0.2）
        self.BINARY_DATA_PRINTABLE_RATIO = config.get(
            'recording.encryption_detection.binary_printable_ratio_threshold',
            default=0.7
        )
        self.DICT_VALUE_MIN_LENGTH = 20
        self.DICT_CONFIDENCE_THRESHOLD = 0.7
        self.DICT_CONFIDENCE_MULTIPLIER = 0.9

        # 🔧 从配置读取熵值阈值（替换硬编码的 4.5）
        self.entropy_threshold_random_string = config.get(
            'recording.encryption_detection.entropy_threshold_random_string',
            default=4.5
        )

    # 加密字段名称
    ENCRYPTED_FIELD_NAMES = [
        "encrypted_data",
        "cipher_text",
        "encrypted",
        "ciphertext",
        "encrypted_payload",
        "secret",
    ]

    def detect(self, data: str) -> EncryptionDetectionResult:
        """
        检测数据是否被加密

        Args:
            data: 要检测的字符串数据

        Returns:
            加密检测结果
        """
        if not data or not isinstance(data, str):
            return EncryptionDetectionResult(
                is_encrypted=False,
                encryption_type=None,
                confidence=0.0,
                reason="Data is empty or not a string",
            )

        # 检查 1: 长度异常的随机字符串
        if self._is_long_random_string(data):
            return EncryptionDetectionResult(
                is_encrypted=True,
                encryption_type=EncryptionType.UNKNOWN,
                confidence=self.CONFIDENCE_RANDOM_STRING,
                reason="Long random string detected",
            )

        # 检查 2: Base64 编码
        if self._is_base64_encoded(data):
            # 尝试解码验证
            try:
                decoded = base64.b64decode(data, validate=True)
                # 如果解码后是不可打印字符，很可能是加密数据
                if self._is_binary_data(decoded):
                    return EncryptionDetectionResult(
                        is_encrypted=True,
                        encryption_type=EncryptionType.BASE64,
                        confidence=self.CONFIDENCE_BASE64_BINARY,
                        reason="Base64 encoded binary data",
                    )
            except Exception:
                pass

        # 检查 3: OpenSSL AES 加密特征
        if self.PATTERNS["open_ssl_aes"].match(data):
            return EncryptionDetectionResult(
                is_encrypted=True,
                encryption_type=EncryptionType.AES,
                confidence=self.CONFIDENCE_HIGH,
                reason="OpenSSL AES encryption pattern detected",
            )

        # 检查 4: 长十六进制字符串
        if self.PATTERNS["hex_long"].match(data):
            return EncryptionDetectionResult(
                is_encrypted=True,
                encryption_type=EncryptionType.UNKNOWN,
                confidence=self.CONFIDENCE_LONG_HEX,
                reason="Long hex string detected",
            )

        # 默认：未检测到加密
        return EncryptionDetectionResult(
            is_encrypted=False,
            encryption_type=None,
            confidence=0.0,
            reason="No encryption patterns detected",
        )

    def detect_in_dict(self, data: dict) -> EncryptionDetectionResult:
        """
        在字典中检测加密字段

        Args:
            data: 要检测的字典

        Returns:
            加密检测结果
        """
        if not isinstance(data, dict):
            return EncryptionDetectionResult(
                is_encrypted=False,
                encryption_type=None,
                confidence=0.0,
                reason="Data is not a dictionary",
            )

        # 检查是否有加密字段名
        for key in data.keys():
            if key.lower() in self.ENCRYPTED_FIELD_NAMES:
                return EncryptionDetectionResult(
                    is_encrypted=True,
                    encryption_type=EncryptionType.UNKNOWN,
                    confidence=self.CONFIDENCE_ENCRYPTED_FIELD,
                    reason=f"Encrypted field name detected: {key}",
                )

        # 检查所有字符串值
        for key, value in data.items():
            if isinstance(value, str) and len(value) > self.DICT_VALUE_MIN_LENGTH:
                result = self.detect(value)
                if result.is_encrypted and result.confidence > self.DICT_CONFIDENCE_THRESHOLD:
                    return EncryptionDetectionResult(
                        is_encrypted=True,
                        encryption_type=result.encryption_type,
                        confidence=result.confidence
                        * self.DICT_CONFIDENCE_MULTIPLIER,  # 略微降低置信度
                        reason=f"Encrypted value in field: {key}",
                    )

        return EncryptionDetectionResult(
            is_encrypted=False,
            encryption_type=None,
            confidence=0.0,
            reason="No encryption detected in dictionary",
        )

    def _is_long_random_string(self, data: str) -> bool:
        """检测是否为长随机字符串"""
        if len(data) < self.MIN_RANDOM_STRING_LENGTH:
            return False

        # 计算字符熵（Shannon entropy）
        from collections import Counter

        import math

        char_counts = Counter(data)
        entropy = -sum(
            (count / len(data)) * math.log2(count / len(data)) for count in char_counts.values()
        )

        # 🔧 使用配置中的熵值阈值（替换硬编码的 4.5）
        return entropy > self.entropy_threshold_random_string

    def _is_base64_encoded(self, data: str) -> bool:
        """检测是否为 Base64 编码"""
        # 基本格式检查
        if not self.PATTERNS["base64"].match(data):
            return False

        # 长度应该是 4 的倍数
        if len(data) % 4 != 0:
            return False

        return True

    def _is_binary_data(self, data: bytes) -> bool:
        """检测是否为二进制数据"""
        # 检查不可打印字符的比例
        printable_ratio = sum(32 <= byte <= 126 for byte in data) / len(data)

        # 如果可打印字符少于阈值，认为是二进制数据
        return printable_ratio < self.BINARY_DATA_PRINTABLE_RATIO
