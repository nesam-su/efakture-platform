from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


def test_password_roundtrip():
    from app.core.security import hash_password, verify_password

    encoded = hash_password("duga-i-jaka-lozinka")
    assert verify_password("duga-i-jaka-lozinka", encoded)
    assert not verify_password("pogresna-lozinka", encoded)


def test_fernet_key_shape():
    assert len(Fernet.generate_key()) == 44


def test_invitation_secret_is_stored_only_as_hash():
    from app.core.security import create_invitation_secret, hash_invitation_secret

    secret, digest = create_invitation_secret()
    assert secret != digest
    assert len(digest) == 64
    assert hash_invitation_secret(secret) == digest


def test_public_pages(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("APP_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    from app.main import app

    client = TestClient(app, base_url="http://localhost")
    assert client.get("/health/live").json() == {"status": "ok"}
    response = client.get("/")
    assert response.status_code == 200
    assert "eDokumenti" in response.text
