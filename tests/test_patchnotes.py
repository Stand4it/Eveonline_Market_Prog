import unittest

from eve_profit import patchnotes


class PatchNotes(unittest.TestCase):
    def test_sections_split_by_date_and_money_lines_are_picked(self):
        t = patchnotes._text("<p>Intro</p><h2>PATCH NOTES FOR 2026-10-20.1</h2><ul><li>Increased drop rates across Crimson Harvest sites, sold to NPC buyers for ISK</li>"
                             "<li>Fixed a typo in a tooltip</li></ul><h2>PATCH NOTES FOR 2026-10-16.1</h2><p>Broker fee reduced in Caldari space</p>")
        parts = patchnotes.SECTION.split(t)
        self.assertEqual(parts[1::2], ["2026-10-20.1", "2026-10-16.1"])
        rel = patchnotes.relevant(parts[2])
        self.assertTrue(any("drop rates" in x for x in rel))
        self.assertFalse(any("tooltip" in x for x in rel))
        self.assertTrue(patchnotes.relevant(parts[4]))


if __name__ == "__main__":
    unittest.main()
