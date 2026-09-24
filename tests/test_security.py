from uuid import uuid4

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


def test_access_token_binds_user_to_revocable_session(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "t" * 48)
    monkeypatch.setenv("APP_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    from app.core.config import get_settings
    from app.core.security import create_access_token, decode_access_token

    get_settings.cache_clear()
    user_id, session_id = uuid4(), uuid4()
    claims = decode_access_token(create_access_token(user_id, session_id))
    assert claims.user_id == user_id
    assert claims.session_id == session_id
    get_settings.cache_clear()


def test_login_throttle_key_is_normalized_and_ip_scoped():
    from app.core.security import login_throttle_key

    assert login_throttle_key(" USER@example.rs ", "127.0.0.1") == login_throttle_key(
        "user@example.rs", "127.0.0.1"
    )
    assert login_throttle_key("user@example.rs", "127.0.0.1") != login_throttle_key(
        "user@example.rs", "127.0.0.2"
    )


def test_totp_matches_rfc_6238_sha1_vector():
    from app.core.security import totp_code

    # RFC 6238 Appendix B secret "12345678901234567890", timestamp 59.
    assert totp_code("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", timestamp=59, digits=8) == "94287082"


def test_totp_rejects_replayed_counter():
    from app.core.security import totp_code, verify_totp

    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    code = totp_code(secret, timestamp=59)
    counter = verify_totp(secret, code, timestamp=59)
    assert counter == 1
    assert verify_totp(secret, code, timestamp=59, last_counter=counter) is None


def test_recovery_codes_are_distinct_and_hashable():
    from app.core.security import generate_recovery_codes, hash_one_time_secret

    codes = generate_recovery_codes()
    assert len(codes) == len(set(codes)) == 10
    assert all(len(hash_one_time_secret(code)) == 64 for code in codes)


def test_public_pages(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("APP_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    from app.main import app

    client = TestClient(app, base_url="http://localhost")
    assert client.get("/health/live").json() == {"status": "ok"}
    response = client.get("/")
    assert response.status_code == 200
    assert "eDokumenti" in response.text
    assert 'id="document-dialog"' in response.text
    assert 'id="organization-select"' in response.text
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/security.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/favicon.svg").status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_csv_environment_lists(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "x" * 48)
    monkeypatch.setenv("APP_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("APP_ALLOWED_HOSTS", "localhost,127.0.0.1")
    monkeypatch.setenv("APP_CORS_ORIGINS", "https://app.example.rs,https://admin.example.rs")
    from app.core.config import Settings

    settings = Settings()
    assert settings.allowed_hosts == ["localhost", "127.0.0.1"]
    assert settings.cors_origins == ["https://app.example.rs", "https://admin.example.rs"]
