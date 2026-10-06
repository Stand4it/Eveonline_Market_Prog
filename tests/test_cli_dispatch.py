import re
import unittest


class DispatchTests(unittest.TestCase):
    def test_every_command_has_a_branch(self):
        """A bad edit once deleted 22 command branches and `bestprice` silently ran a scan instead."""
        s = open("eve_profit/cli.py").read()
        handled = set(re.findall(r'a\.cmd == "(\w+)"', s))
        for grp in re.findall(r'a\.cmd in \(([^)]*)\)', s):
            handled |= set(re.findall(r'"(\w+)"', grp))
        choices = set(re.findall(r'"(\w+)"', re.search(r'choices=\[([^\]]*)\]', s).group(1)))
        self.assertEqual(choices - handled - {"plan", "scan", "watch"}, set())


if __name__ == "__main__":
    unittest.main()
