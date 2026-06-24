from dataclasses import dataclass
from enum import Enum


class DataEnvironment(str, Enum):
    DEMO = "demo"
    PROD_PUBLIC = "prod_public"
    HISTORICAL = "historical"
    SYNTHETIC = "synthetic"


class DataUseCase(str, Enum):
    INTEGRATION_TESTING = "integration_testing"
    MARKET_RESEARCH = "market_research"
    BACKTESTING = "backtesting"
    EXECUTION_TESTING = "execution_testing"


class InvalidDataSourceError(ValueError):
    pass


@dataclass(frozen=True)
class DataSourceProfile:
    environment: DataEnvironment
    suitable_for_research: bool
    suitable_for_execution_testing: bool
    suitable_for_backtesting: bool
    notes: str


DEMO_PROFILE = DataSourceProfile(
    environment=DataEnvironment.DEMO,
    suitable_for_research=False,
    suitable_for_execution_testing=True,
    suitable_for_backtesting=False,
    notes=(
        "Demo data is used for API integration and order-lifecycle testing only. "
        "Liquidity, trade-frequency, and fill metrics are not representative."
    ),
)

PROD_PUBLIC_PROFILE = DataSourceProfile(
    environment=DataEnvironment.PROD_PUBLIC,
    suitable_for_research=True,
    suitable_for_execution_testing=False,
    suitable_for_backtesting=False,
    notes=(
        "Production public market data is used for real market-universe, spread, "
        "depth, and order-book analytics."
    ),
)

HISTORICAL_PROFILE = DataSourceProfile(
    environment=DataEnvironment.HISTORICAL,
    suitable_for_research=True,
    suitable_for_execution_testing=False,
    suitable_for_backtesting=True,
    notes=(
        "Historical data is used for backtesting, calibration, realized outcomes, "
        "and trade-replay analysis."
    ),
)

SYNTHETIC_PROFILE = DataSourceProfile(
    environment=DataEnvironment.SYNTHETIC,
    suitable_for_research=False,
    suitable_for_execution_testing=False,
    suitable_for_backtesting=False,
    notes="Synthetic data is deterministic test data only.",
)

PROFILES = {
    profile.environment: profile
    for profile in (
        DEMO_PROFILE,
        PROD_PUBLIC_PROFILE,
        HISTORICAL_PROFILE,
        SYNTHETIC_PROFILE,
    )
}


def get_data_source_profile(environment: str | DataEnvironment) -> DataSourceProfile:
    return PROFILES[DataEnvironment(environment)]


def require_research_validity(profile: DataSourceProfile) -> None:
    if not profile.suitable_for_research:
        raise InvalidDataSourceError(
            f"{profile.environment.value} is not suitable for market microstructure research."
        )


def require_backtesting_validity(profile: DataSourceProfile) -> None:
    if not profile.suitable_for_backtesting:
        raise InvalidDataSourceError(
            f"{profile.environment.value} is not suitable for backtesting."
        )
