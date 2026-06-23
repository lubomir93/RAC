# tests/test_executor.py

import unittest
import pandas as pd
from tests.test_base import BaseTest
import ra_compiler.cli as cli
import ra_compiler.executor as exe
# import ra_compiler.exceptions as exceptions

class TestSortHelpers(unittest.TestCase):

    def test_exec_sort_preserves_secondary_order(self):
        df = pd.DataFrame({
            "month": [2, 1, 3, 12, 9, 10, 11, 8],
            "year": [2026, 2026, 2026, 2025, 2025, 2025, 2025, 2025],
            "sum_amount": [6039.26, 2792.66, 2340.47, 1027.11, 4184.09, 2251.96, 2353.37, 78.21],
        })
        expr = {
            "table_alias": "_rac_q",
            "sort_attributes": [("year", False), ("month", False)],
        }

        result = exe.exec_sort(expr, exe.NamedDataFrame("grouped", df))

        self.assertEqual(
            list(zip(result.df["year"], result.df["month"])),
            [(2026, 3), (2026, 2), (2026, 1), (2025, 12), (2025, 11),
             (2025, 10), (2025, 9), (2025, 8)]
        )


class TestListHelpers(unittest.TestCase):

    def test_exec_list_groups_database_and_rac_relations(self):
        original_run_query = exe.run_query
        original_list_relations_query = exe.list_relations_query
        exe.saved_results.clear()
        try:
            exe.run_query = lambda query: (
                ["category", "relation_name"],
                [
                    ("tables", "transaction"),
                    ("temporary_tables", "tmp_transaction"),
                    ("views", "transaction_view"),
                    ("materialized_views", "monthly_transaction_summary"),
                ]
            )
            exe.list_relations_query = lambda: "LIST_RELATIONS"
            exe.saved_results["_rac_q0"] = exe.NamedDataFrame("_rac_q0", pd.DataFrame(), save=False)
            exe.saved_results["ProjectedTransactions"] = exe.NamedDataFrame(
                "ProjectedTransactions", pd.DataFrame(), save=True
            )

            listing = exe.exec_list()

            self.assertEqual(listing, {
                "tables": ["transaction"],
                "temporary_tables": ["tmp_transaction"],
                "views": ["transaction_view"],
                "materialized_views": ["monthly_transaction_summary"],
                "rac_virtual_views": ["ProjectedTransactions"],
            })
            self.assertNotIn("_rac_q0", exe.saved_results)
        finally:
            exe.run_query = original_run_query
            exe.list_relations_query = original_list_relations_query
            exe.saved_results.clear()

    def test_exec_list_omits_empty_categories(self):
        original_run_query = exe.run_query
        original_list_relations_query = exe.list_relations_query
        exe.saved_results.clear()
        try:
            exe.run_query = lambda query: (["category", "relation_name"], [("tables", "T")])
            exe.list_relations_query = lambda: "LIST_RELATIONS"

            self.assertEqual(exe.exec_list(), {"tables": ["T"]})
        finally:
            exe.run_query = original_run_query
            exe.list_relations_query = original_list_relations_query
            exe.saved_results.clear()


class TestLimitHelpers(unittest.TestCase):

    def test_exec_limit_returns_first_rows(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        expr = {"table_alias": "_rac_q", "count": 2}

        result = exe.exec_limit(expr, exe.NamedDataFrame("T", df))

        pd.testing.assert_frame_equal(
            result.df.reset_index(drop=True),
            pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        )

    def test_exec_limit_rejects_negative_counts(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        expr = {"table_alias": "_rac_q", "count": -1}

        with self.assertRaises(ValueError):
            exe.exec_limit(expr, exe.NamedDataFrame("T", df))


class TestJoinHelpers(unittest.TestCase):

    def test_qualified_condition_uses_table_names_for_duplicate_columns(self):
        left = exe.NamedDataFrame("A", pd.DataFrame({"x": [1], "y": [7]}))
        right = exe.NamedDataFrame("B", pd.DataFrame({"x": [9], "y": [1]}))
        expr = {
            "table_alias": "J",
            "join_type": "inner",
            "table1": "A",
            "table2": "B",
            "condition": {
                "type": "comp_cond",
                "left": ["B", "y"],
                "op": "=",
                "right": ["A", "x"],
            },
        }

        result = exe.exec_join(expr, left, right)

        pd.testing.assert_frame_equal(
            result.df,
            pd.DataFrame({"x_L": [1], "y_L": [7], "x_R": [9], "y_R": [1]})
                .convert_dtypes(),
        )

    def test_qualified_condition_does_not_match_opposite_duplicate_columns(self):
        left = exe.NamedDataFrame("A", pd.DataFrame({"x": [1], "y": [7]}))
        right = exe.NamedDataFrame("B", pd.DataFrame({"x": [7], "y": [9]}))
        expr = {
            "table_alias": "J",
            "join_type": "inner",
            "table1": "A",
            "table2": "B",
            "condition": {
                "type": "comp_cond",
                "left": ["B", "y"],
                "op": "=",
                "right": ["A", "x"],
            },
        }

        result = exe.exec_join(expr, left, right)

        self.assertTrue(result.df.empty)

    def test_left_join_does_not_match_partial_null_composite_keys(self):
        left = exe.NamedDataFrame("A", pd.DataFrame({"a": [1], "b": [pd.NA], "v": ["left"]}))
        right = exe.NamedDataFrame("B", pd.DataFrame({"a": [1], "b": [pd.NA], "w": ["right"]}))
        expr = {
            "table_alias": "J",
            "join_type": "left",
            "attributes": ["a", "b"],
        }

        result = exe.exec_join(expr, left, right)

        expected_left_side = pd.DataFrame({
            "a": [1],
            "b": [pd.NA],
            "v": ["left"],
        }).convert_dtypes()
        pd.testing.assert_frame_equal(result.df[["a", "b", "v"]], expected_left_side, check_dtype=False)
        self.assertTrue(pd.isna(result.df.loc[0, "w"]))

    def test_outer_join_splits_partial_null_composite_key_rows(self):
        left = exe.NamedDataFrame("A", pd.DataFrame({"a": [1], "b": [pd.NA], "v": ["left"]}))
        right = exe.NamedDataFrame("B", pd.DataFrame({"a": [1], "b": [pd.NA], "w": ["right"]}))
        expr = {
            "table_alias": "J",
            "join_type": "outer",
            "attributes": ["a", "b"],
        }

        result = exe.exec_join(expr, left, right)

        expected = pd.DataFrame({
            "a": [1, 1],
            "b": [pd.NA, pd.NA],
            "v": ["left", pd.NA],
            "w": [pd.NA, "right"],
        }).convert_dtypes()
        pd.testing.assert_frame_equal(result.df, expected, check_dtype=False)


class TestExecutor(BaseTest):

    def test_count_star_counts_all_rows_even_when_all_values_are_null(self):
        df = pd.DataFrame({"a": [None, None], "b": [None, 1]})
        expr = {
            "table_alias": "_rac_q",
            "attributes": [],
            "aggr_cond": [{"aggr": "count", "attr": ["*"]}],
        }

        result = exe.exec_group(expr, exe.NamedDataFrame("T", df))

        self.assertEqual(result.df.iloc[0, 0], 2)

    def test_evaluate_comparison_cond_with_null_literals_returns_false(self):
        df = pd.DataFrame({"a": [1, 2]})
        cond = {"op": "=", "left": None, "right": None}

        result = exe.evaluate_comparison_cond(df, cond)

        self.assertTrue(result.dtype == "boolean")
        self.assertEqual(result.tolist(), [False, False])

    def test_execute_empty(self):
        self.assertRaises(ValueError, exe.execute, None)
        self.assertRaises(ValueError, exe.execute, {})
        self.assertRaises(ValueError, exe.execute, "")

    def test_prepare_cols_for_merge(self):
        cli.handle_query("(T /x T)->T3")

        ndf1 = exe.load_table("T3")
        ndf2 = exe.load_table("T")

        exe.prepare_for_merge_op(ndf1.df, ndf2.df)

        expected_left_cols = ["age_L_L", "b_L_L", "c_L_L", "age_R_L", "b_R_L", "c_R_L",]
        expected_right_cols = ["age_R", "b_R", "c_R",]

        for col in expected_left_cols:
            self.assertIn(col, ndf1.df.columns,
                          f"Expected '{col}' in columns {list( ndf1.df.columns)}")

        for col in expected_right_cols:
            self.assertIn(col, ndf2.df.columns,
                          f"Expected '{col}' in columns {list( ndf2.df.columns)}")

if __name__ == "__main__":
    unittest.main()
