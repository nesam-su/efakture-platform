from __future__ import annotations

from typing import Literal

from app.models import Provider

IntegrationEnvironment = Literal["demo", "production"]

OFFICIAL_INTEGRATION_URLS: dict[Provider, dict[IntegrationEnvironment, str]] = {
    Provider.sef: {
        "demo": "https://demoefaktura.mfin.gov.rs",
        "production": "https://efaktura.mfin.gov.rs",
    },
    Provider.eotpremnice: {
        "demo": "https://api.demoeotpremnica.mfin.gov.rs",
        "production": "https://api.eotpremnica.mfin.gov.rs",
    },
}


def integration_base_url(provider: Provider, environment: IntegrationEnvironment) -> str:
    """Return a trusted government endpoint instead of accepting an arbitrary URL."""
    return OFFICIAL_INTEGRATION_URLS[provider][environment]
