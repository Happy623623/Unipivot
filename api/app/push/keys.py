"""VAPID 키 (F-33). 푸시 서비스에 "이 서버가 보냈다"고 밝히는 P-256 키 한 쌍이다.

키는 **설정에서만** 읽는다(`api/.env`). 레포에는 넣지 않는다 — `.env.example`에는 빈 칸만 있다.
키가 없으면 푸시를 보내지 않고 알림함에만 쌓는다(명세 12장). 서버는 그래도 뜬다.

키를 만들려면 api 폴더에서:

    uv run python -m app.push.keys

찍힌 두 줄을 `api/.env`에 붙이고, 공개 키는 web의 `NEXT_PUBLIC_VAPID_PUBLIC_KEY`에도 넣는다
(브라우저가 `PushManager.subscribe()`에 쓴다). **비밀 키는 서버에만 둔다.**
"""

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

CURVE = ec.SECP256R1()
_PRIVATE_BYTES = 32


def b64u(raw: bytes) -> str:
    """패딩 없는 base64url. 웹 푸시의 모든 키·값이 이 꼴이다."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64u(value: str) -> bytes:
    """패딩이 빠진 base64url도 읽는다(브라우저가 패딩 없이 준다)."""
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode())


@dataclass(frozen=True)
class VapidKeys:
    """서버의 VAPID 키 한 쌍과 연락처(`mailto:` 또는 주소)."""

    private_key: ec.EllipticCurvePrivateKey
    public_bytes: bytes  # 65바이트 비압축 공개 키(푸시 서비스에 그대로 보낸다)
    subject: str

    @property
    def public_b64(self) -> str:
        return b64u(self.public_bytes)


def load_keys(*, private_key: str, subject: str) -> VapidKeys | None:
    """설정 값에서 키를 읽는다. 비었거나 읽을 수 없으면 None이다(푸시를 건너뛴다).

    공개 키는 비밀 키에서 다시 만든다 — 설정에 둘을 따로 두면 서로 안 맞는 짝이 들어갈 수 있다.
    """
    if not private_key or not subject:
        return None
    try:
        raw = unb64u(private_key)
        if len(raw) != _PRIVATE_BYTES:
            raise ValueError(f"비밀 키가 {_PRIVATE_BYTES}바이트가 아니에요: {len(raw)}")
        key = ec.derive_private_key(int.from_bytes(raw, "big"), CURVE)
    except Exception:
        return None
    return VapidKeys(
        private_key=key,
        public_bytes=key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint),
        subject=subject,
    )


def generate_keys() -> tuple[str, str]:
    """새 키 한 쌍(비밀, 공개)을 base64url로. 시험과 아래 CLI가 쓴다."""
    key = ec.generate_private_key(CURVE)
    private = key.private_numbers().private_value.to_bytes(_PRIVATE_BYTES, "big")
    public = key.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return b64u(private), b64u(public)


def main() -> None:
    private, public = generate_keys()
    print("# api/.env 에 붙여 주세요 (비밀 키는 서버에만 둡니다)")
    print(f"VAPID_PRIVATE_KEY={private}")
    print("VAPID_SUBJECT=mailto:본인메일@hanyang.ac.kr")
    print()
    print("# web/.env.local 에 붙여 주세요 (브라우저가 구독할 때 씁니다)")
    print(f"NEXT_PUBLIC_VAPID_PUBLIC_KEY={public}")


if __name__ == "__main__":
    main()
