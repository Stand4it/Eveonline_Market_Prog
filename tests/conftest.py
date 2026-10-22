import pytest

from eve_profit import orders


@pytest.fixture(autouse=True)
def _fresh_order_books():
    """Tests write orders straight into fresh DBs: the per-run order-book cache must not carry over between tests."""
    orders.bump()
    yield
    orders.bump()


@pytest.fixture(autouse=True)
def _no_real_accepted_missions(monkeypatch):
    """The owner's real agent_offers.json may hold ACCEPTED missions; they would outrank every step a test checks."""
    from eve_profit import agentchain
    monkeypatch.setattr(agentchain, "accepted_candidate", lambda *a, **k: None)
