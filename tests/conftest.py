import pytest

from stagecraft.config import load_config


@pytest.fixture(scope="session")
def cfg():
    return load_config()
