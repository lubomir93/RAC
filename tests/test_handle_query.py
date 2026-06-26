import contextlib
import io
import unittest
import pandas as pd
from tests.test_base import BaseTest
import ra_compiler.cli as cli

class TestBracketHighlighting(unittest.TestCase):

    def test_find_matching_bracket_returns_opening_index(self):
        self.assertEqual(cli.find_matching_bracket("(a{b})", 4), 2)
        self.assertEqual(cli.find_matching_bracket("(a{b})", 5), 0)
        self.assertEqual(cli.find_matching_bracket("((a))", 3), 1)
        self.assertEqual(cli.find_matching_bracket("((a))", 4), 0)
        self.assertEqual(cli.find_matching_bracket("[a]", 2), 0)

    def test_find_matching_bracket_returns_negative_one_without_match(self):
        self.assertEqual(cli.find_matching_bracket("a)", 1), -1)
        self.assertEqual(cli.find_matching_bracket("(a)", 1), -1)


class TestClearCommand(unittest.TestCase):

    def test_clear_screen_uses_platform_clear_command(self):
        original_system = cli.os.system
        calls = []

        try:
            cli.os.system = lambda command: calls.append(command)
            cli.clear_screen()
        finally:
            cli.os.system = original_system

        self.assertEqual(calls, ["cls" if cli.os.name == "nt" else "clear"])

    def test_clear_command_aliases_clear_screen(self):
        original_clear_screen = cli.clear_screen
        calls = []

        try:
            cli.clear_screen = lambda: calls.append("clear")

            for alias in ["clear", "/clear", "\\clear"]:
                with self.subTest(alias=alias):
                    self.assertTrue(cli.check_if_help_command(alias))

            self.assertEqual(calls, ["clear", "clear", "clear"])
        finally:
            cli.clear_screen = original_clear_screen

    def test_clear_command_does_not_clear_prompt_history(self):
        original_clear_screen = cli.clear_screen
        original_prompt_session = cli.prompt_session
        original_readline = cli.readline

        class FakeHistory:
            def __init__(self):
                self._loaded = False
                self._loaded_strings = ["old prompt"]
                self._storage = ["old prompt"]

        class FakePromptSession:
            def __init__(self, history):
                self.history = history

        class FakeReadline:
            def __init__(self):
                self.cleared = False

            def clear_history(self):
                self.cleared = True

        try:
            history = FakeHistory()
            fake_readline = FakeReadline()
            cli.clear_screen = lambda: None
            cli.prompt_session = FakePromptSession(history)
            cli.readline = fake_readline

            self.assertTrue(cli.check_if_help_command("clear"))

            self.assertEqual(history._loaded_strings, ["old prompt"])
            self.assertEqual(history._storage, ["old prompt"])
            self.assertFalse(history._loaded)
            self.assertFalse(fake_readline.cleared)
        finally:
            cli.clear_screen = original_clear_screen
            cli.prompt_session = original_prompt_session
            cli.readline = original_readline


class TestRunOutput(unittest.TestCase):

    def test_run_prints_only_dataframe_for_query_results(self):
        output = io.StringIO()
        prompts = iter(["(/pi {b} testTable)"])
        result = type("Result", (), {
            "name": "_rac_q1",
            "df": pd.DataFrame({"b": [1]}),
            "save": False,
        })()

        original_prompt_for_query = cli.prompt_for_query
        original_handle_query = cli.handle_query
        original_clean_exit = cli.clean_exit

        def fake_prompt_for_query(prompt='> '):
            try:
                return next(prompts)
            except StopIteration:
                raise EOFError

        def fake_clean_exit(exit_code=0):
            raise SystemExit(exit_code)

        try:
            cli.prompt_for_query = fake_prompt_for_query
            cli.handle_query = lambda query, query_count=0: result
            cli.clean_exit = fake_clean_exit

            with self.assertRaises(SystemExit):
                with contextlib.redirect_stdout(output):
                    cli.run()
        finally:
            cli.prompt_for_query = original_prompt_for_query
            cli.handle_query = original_handle_query
            cli.clean_exit = original_clean_exit

        printed = output.getvalue()
        self.assertNotIn("Execution Result:", printed)
        self.assertNotIn("_rac_q1", printed)
        self.assertIn("b", printed)
        self.assertIn("1", printed)


class TestHandleQuery(BaseTest):

    def _run_and_check(self, query, expected_cols):
        """Helper to run a query and verify columns exist."""

        result = cli.handle_query(query)

        self.assertIsNotNone(result, f"Query returned None: {query}")
        self.assertTrue(hasattr(result, "df"), f"Result missing .df: {query}")

        df = result.df

        for col in expected_cols:
            self.assertIn(col, df.columns, f"Expected '{col}' in columns {list(df.columns)}")

        print(df)
        return df

    def test_handle_query_projection(self):
        """Test handling a projection query."""

        df = self._run_and_check("(/pi {b} testTable)", ["b"])

        expected = pd.DataFrame({"b": [1, 2, 3]})
        pd.testing.assert_frame_equal(df, expected, check_dtype=False, check_index_type=False)

    def test_show_dataframe_returns_nullable_converted_frame(self):
        df = pd.DataFrame({"a": [1, None], "b": ["x", None]}, dtype=object)

        converted = cli.show_dataframe("demo", df)

        self.assertIsNotNone(converted)
        self.assertEqual(str(converted.dtypes["a"]), "Int64")
        self.assertEqual(str(converted.dtypes["b"]), "string")

    def test_sigma_true(self):
        df = self._run_and_check("(/sigma{True} (testTabR))", ["age", "b", "c", "d", "name"])
        self.assertEqual(len(df), 16)

    def test_projection_date_part_functions(self):
        df = self._run_and_check(
            "/pi_{month(tdate), year(tdate) -> txn_year} testTable",
            ["month_tdate", "txn_year"]
        )

        expected = pd.DataFrame({
            "month_tdate": [1, 2, 2, 12],
            "txn_year": [2024, 2024, 2025, 2025],
        })
        pd.testing.assert_frame_equal(df, expected, check_dtype=False, check_index_type=False)

    def test_list_separates_tables_from_rho_views(self):
        cli.saved_results.clear()
        try:
            query_result = cli.handle_query("(/pi {b} testTable)")
            self.assertIsNotNone(query_result)
            self.assertNotIn(query_result.name, cli.saved_results)

            cli.handle_query("(/rho {ProjectedB} (/pi {b} testTable))")
            listing = cli.handle_query("list")

            self.assertIsInstance(listing, dict)
            self.assertIn("tables", listing)
            self.assertIn("rac_virtual_views", listing)
            self.assertIn("testtable", [str(table).lower() for table in listing["tables"]])
            self.assertIn("ProjectedB", [str(view) for view in listing["rac_virtual_views"]])
            self.assertFalse(
                any(str(view).startswith("_rac_q") for view in listing["rac_virtual_views"])
            )
        finally:
            cli.saved_results.clear()


    def test_sigma_false(self):
        df = self._run_and_check("(/sigma{2=4} (testTabR))", ["age", "b", "c", "d", "name"])
        self.assertEqual(len(df), 0)

    def test_selection_age_gt_10(self):
        df = self._run_and_check("(/selection {age > 10} testTabR)", ["age", "b", "c", "d", "name"])
        self.assertTrue((df["age"] > 10).all())

    def test_projection_after_selection(self):
        df = self._run_and_check("(/pi {name, age} (/selection {age > 10} testTabR))", ["name", "age"])
        self.assertTrue((df["age"] > 10).all())

    def test_group_sum_avg(self):
        df = self._run_and_check("(/group {age, b; sum(c), avg(d)} testTabR)",
                                 ["age", "b", "sum_c", "mean_d"])
        self.assertGreater(len(df), 0)

    def test_rho_and_join(self):
        cli.handle_query("(/rho {Tab1} testTabR)")
        cli.handle_query("(/rho {Tab2} T)")
        df = self._run_and_check("(Tab1 /join {Tab1.c = Tab2.b} Tab2)", [])
        self.assertGreater(len(df), 0)

    def test_full_outer_join(self):
        df = self._run_and_check("(testTabR /full_outer_join T)", ["age", "b", "c"])
        self.assertGreater(len(df), 0)

    def test_left_join(self):
        df = self._run_and_check("(testTabR /left T)", ["age", "b", "c"])
        self.assertGreater(len(df), 0)

    def test_right_join_with_rho(self):
        cli.handle_query("(/rho {t2b} (/pi {b} T))")
        df = self._run_and_check("(testTabR /right t2b)", ["age", "b"])
        self.assertGreater(len(df), 0)

    def test_left_join_reverse(self):
        cli.handle_query("(/rho {t2b2} (/pi {b} T))")
        df = self._run_and_check("(t2b2 /left testTabR)", ["b"])
        self.assertGreater(len(df), 0)

    def test_delta_rho(self):
        df = self._run_and_check("(/rho {noDup} (/delta testTabR))", ["age", "b", "c", "d", "name"])
        self.assertLessEqual(len(df), len(pd.read_sql("SELECT * FROM testTabR", self.CONN)))

    def test_division(self):
        df = self._run_and_check("(testTabR /div (/selection {b = 3} (/pi^d {b} T)))",
                                 ["age", "c", "d", "name"])
        self.assertGreaterEqual(len(df), 0)

    def test_various_joins(self):
        join_queries = [
            "(testTabR /join T)",
            "(testTabR /join {testTabR.age=T.age} T)",
            "(testTabR /join {testTabR.b = T.b} T)",
            "(testTabR /join {testTabR.c = T.b} T)",
            "(testTabR /join {b} T)",
            "((/pi {b, c} testTabR) /join {testTabR.b = T.b} (/pi {b} T))",
            "((/pi {b} testTabR) /join {testTabR.b = T.b} (/pi {age, b} T))",
            "((/rho {tab1} (/pi {b, c} testTabR)) /join {tab1.b = tab2.b} (/rho {tab2} (/pi {b} T)))"
        ]
        for q in join_queries:
            with self.subTest(query=q):
                df = self._run_and_check(q, [])
                self.assertGreaterEqual(len(df), 0)

    def test_intersect(self):
        df = self._run_and_check("((/pi{age} testTabR) /intersect (/pi{age} testTabR))", ["age"])
        self.assertGreater(len(df), 0)

    def test_semi_join(self):
        df = self._run_and_check("(T /semi {b} testTabR)", ["age", "b", "c"])
        self.assertGreaterEqual(len(df), 0)

    def test_mass_projection(self):
        various_queries = [
            "(/pi{name} testTabR)",
            "(/pi{name, age, b} testTabR)",
            "(/projection{(2 + c)-> tot} testTabR)",
            "(/projection{age + (2 + c)-> tot} testTabR)",
            "(/projection{age + 2 + c-> tot} testTabR)",
            "(/projection{(age + 2) + c-> tot} testTabR)",
            "(/projection{(age + 2 + c)-> tot} testTabR)",
            "(/projection{age + b -> tot} testTabR)",
            "(/pi{age + b -> tot, name, d} testTabR)",
            "(/projection{testTabR.name, testTabR.b} testTabR) ",
            "(/pi{name, age} (/sigma{age > 3} testTabR))",
            "(/pi{name} (/pi{name, age} testTabR))",
            "(/projection{name, name} testTabR)",
            "(/projection^d{d, c} testTabR)",
            "(/pi{name, age + b -> total}(/sigma{(age + b) > 10}testTabR))",
            "(/projection{name} (/selection{age > 2} (/projection{name, age, b} testTabR)))",
        ]
        for q in various_queries:
            with self.subTest(query=q):
                self._run_and_check(q, [])

    def test_mass_selection(self):
        various_queries = [
            "(/selection{age > 3} testTabR)",
            "(/sigma{age = 12} testTabR)",
            "(/sigma{age > 3 and b < 16} testTabR)",
            "(/selection{age < 8 or age > 15} testTabR)",
            "(/sigma{(age > 3 and b < 16) or name = 'ian'} testTabR)",
            "(/sigma{age > 2} (/sigma{b < 15} testTabR))",
            "(/selection{age > b} testTabR)",
            "(/sigma{testTabR.age >= testTabR.b} testTabR)",
            "(/selection{age + b > 20} testTabR)",
            "(/selection{20 < age + b} testTabR)",
            "(/sigma{(age * 2) < 12} testTabR)",
            "(/selection {age + b > b + c} testTabR)",
            "(/selection {age + b > (b + c)} testTabR)",
            "(/selection{(age + b) > c} testTabR)",
        ]
        for q in various_queries:
            with self.subTest(query=q):
                self._run_and_check(q, [])

if __name__ == "__main__":
    unittest.main()
