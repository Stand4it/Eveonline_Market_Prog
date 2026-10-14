import unittest

from eve_profit import style


class Clock12(unittest.TestCase):
    def test_times_are_12_hour(self):
        self.assertEqual(style.dates("at 2026-10-14 14:38 x").replace("\x1b", "")[:0], "")
        plain = lambda t: __import__("re").sub(r"\x1b\[[0-9;]*m", "", style.dates(t))
        self.assertEqual(plain("2026-10-14 14:38"), "2026-10-14 2:38 PM")
        self.assertEqual(plain("2026-10-14 00:05:09"), "2026-10-14 12:05:09 AM")
        self.assertEqual(plain("12:00"), "12:00 PM")
        self.assertEqual(plain("... 5:30 elapsed"), "... 5:30 elapsed")
        self.assertEqual(plain("2026-10-20"), "2026-10-20")


if __name__ == "__main__":
    unittest.main()
