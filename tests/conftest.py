import os
import time

import pytest


@pytest.fixture
def istanbul():
    """Run a test in UTC+3, whatever this computer's timezone is."""
    yield from _zone("Europe/Istanbul")


@pytest.fixture
def new_york():
    yield from _zone("America/New_York")


def _zone(name):
    old = os.environ.get("TZ")
    os.environ["TZ"] = name
    time.tzset()
    yield
    if old is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = old
    time.tzset()
