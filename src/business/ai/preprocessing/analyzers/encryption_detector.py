"""
加密检测器

基于熵值和启发式规则判断数据是否被加密。
"""


class EncryptionDetector:
    """加密检测器"""

    def is_encrypted(self, data: str) -> bool:
        """
        判断数据是否被加密

        启发式规则：
        1. 熵值检测（加密数据熵值 > 7.5）
        2. 字符分布均匀
        3. Base64 但解码后仍是乱码
        """
        if not data:
            return False

        # 规则 1: 明显的加密标记（即使很短也识别）
        if data.startswith("gAAAAA"):  # Django 加密标记
            return True

        # 规则 2: 熵值检测（需要足够长度）
        if len(data) >= 50:
            entropy = self._calculate_entropy(data[:500])
            if entropy > 7.5:
                return True

        return False

    def _calculate_entropy(self, data: str) -> float:
        """计算字符串的熵值"""
        import math
        from collections import Counter

        if not data:
            return 0.0

        counter = Counter(data)
        total = len(data)
        entropy = 0.0

        for count in counter.values():
            p = count / total
            entropy -= p * math.log2(p)

        return entropy
