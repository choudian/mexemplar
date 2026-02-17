"""快速脚本：移除测试文件中的 emoji"""
import re

# 读取文件
with open('test_orm_sequence.py', 'r', encoding='utf-8') as f:
    content = f.read()

# emoji 替换映射
replacements = {
    '✅': '[OK]',
    '❌': '[FAIL]',
    '⚠️': '[WARN]',
    '📝': '[NOTE]',
    '📋': '[INFO]',
    '🔍': '[CHECK]',
    '🔢': '[SEQ]',
    '🚀': '[START]',
    '🧹': '[CLEAN]',
    '💡': '[TIP]',
}

for emoji, replacement in replacements.items():
    content = content.replace(emoji, replacement)

# 写回文件
with open('test_orm_sequence.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('[OK] 已移除 emoji')
