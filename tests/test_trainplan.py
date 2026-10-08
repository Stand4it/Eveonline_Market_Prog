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


class BookTests(unittest.TestCase):
    def test_untrained_skills_get_a_buy_book_line_with_the_cheapest_nearby_price(self):
        from eve_profit.config import Profile
        from eve_profit.graph import Graph
        from eve_profit.mock import load_mock
        from eve_profit.trainplan import book_list, format_books
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        load_mock(con)
        con.execute("INSERT OR REPLACE INTO types(type_id,name,volume,group_id,skill_rank,skill_primary,skill_secondary) VALUES(900,'Accounting',0.01,1,1,165,166)")
        con.execute("INSERT INTO orders VALUES(991001,900,60000001,1,10000001,0,250000.0,5,1,'',1)")
        con.execute("INSERT INTO orders VALUES(991002,900,60000001,1,10000001,0,300000.0,5,1,'',1)")
        res = plan_training(con, 100, goals=[("Accounting", 2, "tax")])
        books = book_list(con, Graph(con), Profile(current_system="Home"), res)
        self.assertEqual([(b[0], b[1]) for b in books], [("Accounting", 250000.0)])
        self.assertIn("BUY THESE SKILL BOOKS FIRST", format_books(books, 4_000_000))
        con.execute("INSERT INTO character_skills(skill_id,level,sp) VALUES(900,1,250)")
        self.assertEqual(book_list(con, Graph(con), Profile(current_system="Home"), res), [])      # already trained: book owned

        from eve_profit.trainplan import format_top3
        out = format_top3(con, Graph(con), Profile(current_system="Home"), res)
        self.assertIn("TOP 3 RECOMMENDED", out)
        self.assertIn("TOP 3 YOU CAN TRAIN RIGHT NOW", out)
        self.assertIn("you can queue it now", out)                                                # Accounting is owned now
