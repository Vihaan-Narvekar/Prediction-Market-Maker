import pytest

from eventmm.data_sources.base import (
    DataEnvironment,
    InvalidDataSourceError,
    get_data_source_profile,
    require_backtesting_validity,
    require_research_validity,
)


def test_demo_is_not_research_valid():
    profile = get_data_source_profile(DataEnvironment.DEMO)

    with pytest.raises(InvalidDataSourceError):
        require_research_validity(profile)


def test_production_public_is_research_valid():
    profile = get_data_source_profile(DataEnvironment.PROD_PUBLIC)

    require_research_validity(profile)


def test_historical_is_backtesting_valid():
    profile = get_data_source_profile(DataEnvironment.HISTORICAL)

    require_backtesting_validity(profile)
