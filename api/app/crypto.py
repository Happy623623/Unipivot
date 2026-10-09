"""Google·LMS 토큰 암호화 (PRD 7장 토큰 보안).

TOKEN_ENCRYPTION_KEY에는 키를 쉼표로 여러 개 둘 수 있다. 첫 번째 키로 암호화하고 모든 키로 복호화한다.
키를 바꿀 때는 "새키,옛키"로 두고, 저장된 토큰을 rotate()로 다시 암호화한 뒤 옛 키를 뺀다.
"""

from cryptography.fernet import Fernet, MultiFernet


def _fernet(keys: str) -> MultiFernet:
    parts = [key.strip() for key in keys.split(",") if key.strip()]
    if not parts:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY가 비어 있어요. api/.env.example을 보고 키를 만드세요."
        )
    return MultiFernet([Fernet(key) for key in parts])


def encrypt(value: str, keys: str) -> str:
    return _fernet(keys).encrypt(value.encode()).decode()


def decrypt(value: str, keys: str) -> str:
    return _fernet(keys).decrypt(value.encode()).decode()


def rotate(value: str, keys: str) -> str:
    """옛 키로 암호화된 값을 첫 번째(새) 키로 다시 암호화한다."""
    return _fernet(keys).rotate(value.encode()).decode()
