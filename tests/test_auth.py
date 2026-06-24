# tests/test_auth.py

from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from eventmm.kalshi.auth import KalshiAuth


def test_auth_headers_have_required_fields(tmp_path: Path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_path = tmp_path / "test.key"

    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    auth = KalshiAuth(api_key_id="test-key", private_key_path=key_path)
    headers = auth.sign_headers(
        "GET", "https://external-api.demo.kalshi.co/trade-api/v2/markets?limit=10"
    )

    assert "KALSHI-ACCESS-KEY" in headers
    assert "KALSHI-ACCESS-TIMESTAMP" in headers
    assert "KALSHI-ACCESS-SIGNATURE" in headers
