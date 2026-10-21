import pytest

from eve_profit import orders


@pytest.fixture(autouse=True)
def _fresh_order_books():
    """Tests write orders straight into fresh DBs: the per-run order-book cache must not carry over between tests."""
    orders.bump()
    yield
    orders.bump()
