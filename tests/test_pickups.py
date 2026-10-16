import json
import os
import tempfile
import unittest

from eve_profit import db, tripplus
from eve_profit.config import Profile
from eve_profit.graph import Graph
from eve_profit.mock import load_mock


class PickupTests(unittest.TestCase):
    def _world(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(881001,'Spare Part',2,1)")
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id) VALUES(881002,'Huge Thing',500,1)")
        con.execute("INSERT INTO inventory VALUES(881001,1,10)")
        con.execute("INSERT INTO inventory VALUES(881002,1,1)")
        return con, Graph(con), Profile(current_system="Home", cargo_m3=100, wallet_isk=1e7, current_location_id=60000001)

    def test_only_what_fits_is_picked_up(self):
        con, g, p = self._world()
        rows = tripplus.pickups(con, g, p, [g.id_of("Home")])
        self.assertEqual([d["item"] for d in rows], ["Spare Part"])           # the 500 m3 item does not fit a 100 m3 hold

    def test_cargo_already_carried_is_not_picked_up_again(self):
        con, g, p = self._world()
        con.execute("INSERT OR REPLACE INTO meta VALUES('cargo_now', ?)", (json.dumps({"881001": 10}),))
        self.assertEqual(tripplus.pickups(con, g, p, [g.id_of("Home")]), [])

    def test_pickup_step_then_quiet_for_two_hours(self):
        con, g, p = self._world()
        txt = tripplus.pickup_step(con, g, p, "Sys05")
        self.assertTrue(txt.startswith("STEP: PICK UP STOCK in Home"))
        tripplus.mark_picked(con, "Home")
        self.assertEqual(tripplus.pickup_step(con, g, p, "Sys05"), "")


if __name__ == "__main__":
    unittest.main()
