"""
敏感数据加密/解密模块

使用 Fernet 对称加密（AES-128-CBC + HMAC-SHA256），符合数据安全最佳实践。
密钥自动生成并存储在 data/.secret_key 中（已加入 .gitignore）。

加密后的值以 "ENC:" 前缀标识，解密时自动识别。

用法：
    from src.utils.crypto import encrypt, decrypt, is_encrypted

    cipher = encrypt("user@qq.com")        # → "ENC:gAAAAABm..."
    plain  = decrypt(cipher)               # → "user@qq.com"
    plain  = decrypt("user@qq.com")        # → "user@qq.com"（明文直接返回）
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# 加密值前缀，用于标识已加密的数据
_ENC_PREFIX = "ENC:"

# 密钥文件路径（尊重 DATA_DIR 环境变量，HF Spaces 用 /data）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR = os.getenv("DATA_DIR", os.path.join(_BASE_DIR, "data"))
_KEY_FILE = os.path.join(_DATA_DIR, ".secret_key")

# 单例 Fernet 实例
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """获取 Fernet 单例实例，首次调用时自动生成/加载密钥"""
    global _fernet
    if _fernet is not None:
        return _fernet

    # 确保目录存在
    key_dir = os.path.dirname(_KEY_FILE)
    os.makedirs(key_dir, exist_ok=True)

    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "r", encoding="utf-8") as f:
            key = f.read().strip()
        try:
            _fernet = Fernet(key.encode())
        except (ValueError, TypeError):
            logger.error("Secret key file is corrupted, generating a new one")
            key = _generate_and_save_key()
            _fernet = Fernet(key.encode())
    else:
        logger.info("Secret key not found, generating new key...")
        key = _generate_and_save_key()
        _fernet = Fernet(key.encode())

    return _fernet


def _generate_and_save_key() -> str:
    """生成新的 Fernet 密钥并保存到文件"""
    key = Fernet.generate_key().decode()
    # 限制文件权限（仅当前用户可读写）
    fd = os.open(_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, key.encode())
    finally:
        os.close(fd)
    logger.info(f"New secret key generated and saved to {_KEY_FILE}")
    return key


def is_encrypted(value: str) -> bool:
    """检查值是否已加密（以 ENC: 前缀开头）"""
    if not value:
        return False
    return value.startswith(_ENC_PREFIX)


def encrypt(plaintext: str) -> str:
    """加密明文

    Args:
        plaintext: 待加密的明文字符串

    Returns:
        加密后的字符串，格式为 "ENC:<base64_token>"
    """
    if not plaintext:
        return plaintext
    if is_encrypted(plaintext):
        return plaintext  # 已加密，不重复加密
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return _ENC_PREFIX + token.decode("ascii")


def decrypt(ciphertext: str) -> str:
    """解密密文

    如果输入不是加密格式（没有 ENC: 前缀），则原样返回（向后兼容）。

    Args:
        ciphertext: 加密字符串或明文字符串

    Returns:
        解密后的明文字符串
    """
    if not ciphertext:
        return ciphertext
    if not is_encrypted(ciphertext):
        return ciphertext  # 明文直接返回（向后兼容）
    token = ciphertext[len(_ENC_PREFIX):]
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt value (invalid token or wrong key)")
        return ""


def encrypt_if_needed(value: str) -> str:
    """如果值非空且未加密，则加密；否则原样返回"""
    if not value or is_encrypted(value):
        return value
    return encrypt(value)


def decrypt_if_needed(value: str) -> str:
    """如果值已加密，则解密；否则原样返回"""
    if not value:
        return value
    if is_encrypted(value):
        return decrypt(value)
    return value
