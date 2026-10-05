import os
import sqlite3
import tempfile
import unittest

from eve_profit import cli, db


class CharTests(unittest.TestCase):
    def test_new_character_gets_own_db_with_shared_data_only(self):
        d = tempfile.mkdtemp()
        main = os.path.join(d, "eve_profit.db")
        con = db.connect(main)
        con.execute("INSERT INTO systems(system_id,name,security,region_id) VALUES (1,'Hek',0.5,1)")
        con.execute("INSERT INTO inventory(type_id,system_id,quantity) VALUES (34,1,10)")
        con.commit()
        con.close()
        out = os.path.join(d, "eve_profit_fresh.db")
        old_cwd, old_env = os.getcwd(), os.environ.get("EVE_PROFIT_TOKENS")
        try:
            os.chdir(d)
            cli.main(["init", "--db", main, "--char", "fresh"])      # explicit --db: not redirected
            self.assertFalse(os.path.exists(out))
            os.environ["EVE_PROFIT_DB"] = main
            cli.main(["init", "--char", "fresh"])
            self.assertTrue(os.path.exists(out))
            c = sqlite3.connect(out)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM systems").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM inventory").fetchone()[0], 0)
            c.close()
            self.assertEqual(os.environ["EVE_PROFIT_TOKENS"], "tokens_fresh.json")
        finally:
            os.chdir(old_cwd)
            os.environ.pop("EVE_PROFIT_DB", None)
            if old_env is None:
                os.environ.pop("EVE_PROFIT_TOKENS", None)
            else:
                os.environ["EVE_PROFIT_TOKENS"] = old_env


class ActiveTests(unittest.TestCase):
    def setUp(self):
        import json
        self.d = tempfile.mkdtemp()
        self.old = os.getcwd()
        os.chdir(self.d)
        for f, cid, name in (("tokens.json", 1, "Stand Dahldaberg"), ("tokens_fresh.json", 2, "Stand Dahldaberg02")):
            json.dump({"character_id": cid, "character_name": name}, open(f, "w"))

    def tearDown(self):
        os.chdir(self.old)

    def test_picks_the_online_character_and_falls_back_to_last_used(self):
        from unittest import mock
        from eve_profit import active
        with mock.patch.object(active, "is_online", side_effect=lambda cid, k: k["label"] == "fresh"):
            self.assertEqual(active.pick("x", self.d, say=lambda m: None), "fresh")
        with mock.patch.object(active, "is_online", return_value=None):
            self.assertEqual(active.pick("x", self.d, say=lambda m: None), "fresh")     # last used
        active.remember(self.d, "")
        with mock.patch.object(active, "is_online", return_value=None):
            self.assertEqual(active.pick("x", self.d, say=lambda m: None), "")

    def test_char_matches_by_name_and_new_login_is_filed(self):
        import json
        from eve_profit import active
        self.assertEqual(active.match("dahldaberg02"), "fresh")
        json.dump({"character_id": 3, "character_name": "Stand Dahldaberg3"}, open("tokens_pending.json", "w"))
        label, name = active.register()
        self.assertEqual((label, name), ("dahldaberg3", "Stand Dahldaberg3"))
        self.assertTrue(os.path.exists("tokens_dahldaberg3.json"))
        json.dump({"character_id": 2, "character_name": "Stand Dahldaberg02"}, open("tokens_pending.json", "w"))
        self.assertEqual(active.register()[0], "fresh")                  # known character: file replaced


if __name__ == "__main__":
    unittest.main()
