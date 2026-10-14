import ast
import os
import unittest


class NoShadowedHelpersTests(unittest.TestCase):
    def test_run_does_not_assign_a_name_that_is_also_a_module_function(self):
        """`_run` once assigned a local called `_now` while another branch called the module function `_now`: UnboundLocalError on `now`."""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eve_profit", "cli.py")
        tree = ast.parse(open(path, encoding="utf-8").read())
        funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run")
        assigned = {t.id for n in ast.walk(run) if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
        self.assertEqual(sorted(assigned & funcs), [])


if __name__ == "__main__":
    unittest.main()
