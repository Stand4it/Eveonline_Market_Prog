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


if __name__ == "__main__":
    unittest.main()
