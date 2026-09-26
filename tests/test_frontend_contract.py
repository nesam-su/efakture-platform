from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_uses_five_second_safe_auto_refresh():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert "const autoRefreshIntervalMs = 5000" in script
    assert 'document.querySelector("dialog[open]")' in script
    assert "setInterval(autoRefreshActiveView, autoRefreshIntervalMs)" in script


def test_frontend_uses_provider_specific_send_labels():
    script = (PROJECT_ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    template = (PROJECT_ROOT / "app" / "templates" / "index.html").read_text(
        encoding="utf-8"
    )

    assert 'return provider === "sef" ? "SEF" : "eOtpremnice"' in script
    assert "Pošalji u red" not in script
    assert "Pošalji u red" not in template
    assert '/static/app.js?v=0.8.4' in template
