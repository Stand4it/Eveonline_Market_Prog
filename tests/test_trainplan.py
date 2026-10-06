import os, tempfile, unittest
from eve_profit import db
from eve_profit.trainplan import format_trainplan, plan_training


def world():
    con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
    for sid, name, rank in ((1, "Trade", 1), (2, "Accounting", 1), (3, "Broker Relations", 1), (4, "Marketing", 1)):
        con.execute("INSERT INTO types(type_id,name,volume,group_id,skill_rank,skill_primary,skill_secondary) VALUES(?,?,0,1,?,165,166)", (sid, name, rank))
    con.execute("INSERT INTO type_skills VALUES(2,1,3)")      # Accounting needs Trade 3
    con.execute("INSERT INTO type_skills VALUES(3,4,2)")      # Broker Relations needs Marketing 2
    con.execute("INSERT INTO type_skills VALUES(3,1,3)")
    con.execute("INSERT INTO character_skills(skill_id,level,sp) VALUES(1,2,0)")
    con.execute("INSERT INTO char_attrs VALUES('intelligence',25),('memory',25)")
    con.commit()
    return con


class T(unittest.TestCase):
    def test_prerequisites_come_first_and_levels_already_trained_are_skipped(self):
        con = world()
        res = plan_training(con, 100, goals=[("Accounting", 2, "tax"), ("Broker Relations", 1, "fee")])
        order = [(s["skill"], s["level"]) for s in res["steps"]]
        self.assertNotIn(("Trade", 1), order)
        self.assertNotIn(("Trade", 2), order)
        self.assertLess(order.index(("Trade", 3)), order.index(("Accounting", 1)))
        self.assertLess(order.index(("Marketing", 2)), order.index(("Broker Relations", 1)))
        self.assertEqual(order.count(("Trade", 3)), 1)                       # shared prerequisite appears once
        self.assertTrue(all(res["steps"][i]["cum"] <= res["steps"][i + 1]["cum"] for i in range(len(res["steps"]) - 1)))
        self.assertIn("TRAINING PLAN", format_trainplan(res))


if __name__ == "__main__":
    unittest.main()
