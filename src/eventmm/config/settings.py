from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

from eventmm.data_sources.base import (
    DataEnvironment,
    DataSourceProfile,
    get_data_source_profile,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    data_environment: DataEnvironment = DataEnvironment.PROD_PUBLIC
    kalshi_env: str | None = None

    kalshi_api_key_id: str | None = None
    kalshi_private_key_path: Path | None = None
    noaa_cdo_token: str | None = None
    fred_api_key: str | None = None

    kalshi_demo_rest_base_url: str = "https://external-api.demo.kalshi.co/trade-api/v2"
    kalshi_prod_rest_base_url: str = "https://external-api.kalshi.com/trade-api/v2"

    kalshi_demo_ws_url: str = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"
    kalshi_prod_ws_url: str = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"

    data_dir: Path = Path("data")
    log_level: str = "INFO"

    @property
    def rest_base_url(self) -> str:
        if self.data_environment == DataEnvironment.DEMO:
            return self.kalshi_demo_rest_base_url
        return self.kalshi_prod_rest_base_url

    @property
    def ws_url(self) -> str:
        if self.data_environment == DataEnvironment.DEMO:
            return self.kalshi_demo_ws_url
        return self.kalshi_prod_ws_url

    @property
    def data_source_profile(self) -> DataSourceProfile:
        return get_data_source_profile(self.data_environment)


settings = Settings()
