from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import base64
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


@dataclass(frozen=True)
class KalshiAuth:
    api_key_id: str
    private_key_path: Path
    _private_key: RSAPrivateKey = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_private_key", self._load_private_key())

    def _load_private_key(self) -> RSAPrivateKey:
        with open(self.private_key_path, "rb") as f:
            key = serialization.load_pem_private_key(
                f.read(),
                password=None,
            )

        if not isinstance(key, RSAPrivateKey):
            raise TypeError("Kalshi private key must be an RSA private key.")

        return key

    def sign_headers(self, method: str, full_url_or_path: str) -> dict[str, str]:
        timestamp_ms = str(int(time.time() * 1000))
        path = urlparse(full_url_or_path).path
        message = f"{timestamp_ms}{method.upper()}{path}".encode("utf-8")

        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
        }
