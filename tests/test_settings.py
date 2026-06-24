# tests/test_settings.py

from eventmm.config.settings import Settings
from eventmm.data_sources.base import DataEnvironment


def test_default_settings_use_production_public_data():
    s = Settings(_env_file=None)
    assert s.data_environment == DataEnvironment.PROD_PUBLIC
    assert s.data_source_profile.suitable_for_research
    assert "external-api.kalshi.com" in s.rest_base_url


def test_demo_settings_use_demo_endpoint():
    s = Settings(data_environment=DataEnvironment.DEMO, _env_file=None)
    assert not s.data_source_profile.suitable_for_research
    assert "demo" in s.rest_base_url
