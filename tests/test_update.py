import os, tempfile, unittest
from eve_profit import db
from eve_profit.update import build_of, check_update, remember


class T(unittest.TestCase):
    def test_build_parsing_and_status_flow(self):
        con = db.connect(os.path.join(tempfile.mkdtemp(), "t.db"))
        self.assertEqual(build_of('{"_key":"sde","buildNumber":3575015,"releaseDate":"2026-10-02"}'), "3575015")
        self.assertEqual(build_of("plain text build"), "plain text build")
        st, b = check_update(con, lambda: '{"buildNumber": 100}')
        self.assertEqual((st, b), ("first", "100"))
        remember(con, b)
        self.assertEqual(check_update(con, lambda: '{"buildNumber": 100}')[0], "same")
        self.assertEqual(check_update(con, lambda: '{"buildNumber": 101}'), ("new", "101"))


if __name__ == "__main__":
    unittest.main()
