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


@pytest.fixture(autouse=True)
def _no_real_combat_results(monkeypatch, tmp_path):
    """The owner's real fights (data/combat_results.json) recalibrate the combat levels; tests check the guessed numbers."""
    from eve_profit import combatcheck
    monkeypatch.setattr(combatcheck, "RESULTS", str(tmp_path / "combat_results.json"))
