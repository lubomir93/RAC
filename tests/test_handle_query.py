# tests/test_handle_query.py

import unittest
import pandas as pd
from tests.test_base import BaseTest
import ra_compiler.cli as cli

class TestBracketHighlighting(unittest.TestCase):

    def test_find_matching_bracket_returns_opening_index(self):
        self.assertEqual(cli.find_matching_bracket("(a{b})", 4), 2)
        self.assertEqual(cli.find_matching_bracket("(a{b})", 5), 0)

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
