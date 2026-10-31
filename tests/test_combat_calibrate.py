from eve_profit import combatcheck as c


def test_a_real_win_makes_that_fit_pass_and_a_loss_keeps_the_guess():
    req = dict(c.LEVEL1)
    assert not c.passes(req, 18.5, 4149, 0)                          # the guess said this fit loses
    win = [{"level": 1, "dps": 18.5, "ehp": 4149, "tank": 0, "won": True}]
    r = c.calibrate(1, req, win)
    assert c.passes(r, 18.5, 4149, 0) and not c.passes(r, 18.5, 2000, 0)
    assert c.calibrate(1, req, win + [{"level": 1, "dps": 60, "ehp": 9000, "won": False}]) == req
    assert c.calibrate(2, req, win) == req                           # an L1 win says nothing about L2
