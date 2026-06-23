# ra_compiler/executor.py
'''Execute the given translated query and produce a result DF.'''

import pandas as pd
from .mysql import format_identifier, list_relations_query, run_query, table_exists_query
from .utils import print_error, print_warning
from .exceptions import (
    RacException,
    NestedQueryError,
    TableNotFoundError,
    TableAlreadyExists,
    InvalidColumnName,
)

saved_results = {}
#TODO: split this file into more smaller files

class NamedDataFrame():
    """
    Represents a pandas DataFrame wiht an associated name.
    
    Attributes:
        name (str): the name of the dataframe  
        df (pd.DataFrame): the corresponding pandas DataFrame  
    """

    def __init__(self, name, df: pd.DataFrame, save = False, query=None):
        self.name = name
        self.df = df
        self.save = save
        self.query = query

    def __repr__(self):
        return f"NamedDataFrame(name={self.name}, shape={self.df.shape}, " \
            f"save={self.save}, query: {self.query})"

    def __str__(self):
        return f"NamedDataFrame(name={self.name}, shape={self.df.shape}) " \
        f"query: {self.query}"

    def copy(self):
        '''Return a copy of the NamedDataFrame.'''
        return NamedDataFrame(self.name, self.df.copy(), self.save, self.query)

def execute(expr, supress_rename=False):
    '''Execute a given relational algebra query and return a NamedDataFrame.'''

    if not expr:
        raise ValueError("RA expression cannot be empty.")

    operation = None

    try:
        if not isinstance(expr, dict):
            # if it is a string, assume it is a table name and load the table
            if isinstance(expr, str):
                return load_table(expr)

            # otherwise, if it is not a dict through an error
            raise TypeError("RA expression must be a dictionary representing the query.")

        # ensure the expression has an operation type
        operation = expr.get("operation", None)
        if operation is None:
            raise ValueError("RA expression must contain 'operation' key.")

        # recursively get/evaluate the relevant DataFrame(s) for the operation
        ndf, ndf2 = get_tables(expr)
        result = None

        # execute the operation
        match operation:
            # database ops
            case "list":
                result = exec_list()
            case "drop":
                exec_drop(expr)

            # unary ops
            case "projection":
                result = exec_projection(expr, ndf)
            case "selection":
                result = exec_selection(expr, ndf)
            case "group":
                result = exec_group(expr, ndf)
            case "remove_duplicates":
                result = exec_remove_duplicates(expr, ndf)
            case "sort":
                result = exec_sort(expr, ndf)
            case "limit":
                result = exec_limit(expr, ndf)
            case "rename":
                result = exec_rename(expr, ndf, supress_rename)
                if isinstance(result, NamedDataFrame):
                    result.save = True

            # set ops
            case "union":
                result = exec_union(expr, ndf, ndf2)
            case "intersection":
                result = exec_interestion(expr, ndf, ndf2)
            case "difference":
                result = exec_difference(expr, ndf, ndf2)

            # merge ops
            case "cross":
                result = exec_cross(expr, ndf, ndf2)
            case "join":
                result = exec_join(expr, ndf, ndf2)
            case "divide":
                result = exec_divide(expr, ndf, ndf2)

            case _:
                raise ValueError(f"Operation not supported: {expr['operation']}")

        if isinstance(result, NamedDataFrame):
            result.query = expr
        return result

    except TableNotFoundError as e:
        print_error(f"Table '{e.table_name}' does not exist in the database.", e)
        return None
    except NestedQueryError:
        return None
    except RacException as e:
        if not operation:
            operation = "query"

        print_error(f"An error occurred during {operation} execution: {e}", e)
        return None
    except Exception as e:
        print_error(f"{e}", e)
        return None

def get_tables(expr):
    """Ensure the desired table(s) exist depending on the op_type."""

    # ensure the expression has an op type
    op_type = expr.get("op_type", None)
    if op_type is None:
        raise ValueError("RA expression must contain 'op_type' key.")

    match op_type:
        # if a list op, return nothing
        case "db":
            return None, None

        # if a unary op, get and return the one table
        case "unary":
            ndf = load_table(expr.get("table"))
            return ndf, None

        # if a set op, get and check the two tables
        case "set":
            ndf = load_table(expr.get("table1"))
            ndf2 = load_table(expr.get("table2"))

            # ensure the two tables have the same columns
            if not ndf.df.columns.equals(ndf2.df.columns):
                raise ValueError("Set operations require both tables to " \
                                 "have the same columns in the same order.")

            return ndf, ndf2

        # if a merge op, get and return the two tables
        case "merge":
            ndf = load_table(expr.get("table1"))
            ndf2 = load_table(expr.get("table2"))
            return ndf, ndf2

        # otherwise, error
        case _:
            raise ValueError(f"Unsupported operation type: {op_type}")

def load_table(table_name):
    """Return a pandas DataFrame of the desired table from the SQL connection."""

    if table_name is None:
        raise TableNotFoundError()

    # if the table is a string...
    if isinstance(table_name, str):
        # check if it is a table from SQL connection
        if check_sql_for_table(table_name):
            # if the table exists, load and save it
            query = f"SELECT * FROM {format_identifier(table_name)}"
            cols, rows = run_query(query)

            df = pd.DataFrame(rows, columns=cols).convert_dtypes()

        # check if it is a saved result
        elif table_name in saved_results:
            query = saved_results[table_name].query
            ndf = execute(query, supress_rename=True)
            if not ndf:
                raise NestedQueryError
            return ndf
            # return saved_results[table_name].copy()

        # otherwise, error
        else:
            raise TableNotFoundError(table_name)

        # saved as a NamedDataFrame and return a copy
        ndf = NamedDataFrame(table_name, df)
        # saved_results[table_name] = ndf

        return ndf.copy()

    # otherwise, execute the nested operation
    else:
        ndf = execute(table_name)
        if not ndf:
            raise NestedQueryError
        return ndf

def check_sql_for_table(table_name):
    """Return True if the given table name is in the connected sql database."""

    check_query = table_exists_query(table_name)
    result = run_query(check_query)

    if len(result[1]) == 0:
        return False

    return True

## ~~~~~~~~ DATABASE OPERATIONS ~~~~~~~~ ##

def exec_list():
    """Return available database and RAC relations by category."""

    listing = {
        "tables": [],
        "temporary_tables": [],
        "views": [],
        "materialized_views": [],
        "rac_virtual_views": [],
    }

    # Only explicitly saved rename/rho results are RAC virtual views. Older cached
    # plain query results are display-only and should not stay usable/listed.
    for name, ndf in list(saved_results.items()):
        if getattr(ndf, "save", False):
            listing["rac_virtual_views"].append(name)
        else:
            saved_results.pop(name, None)

    query = list_relations_query()
    _, rows = run_query(query)
    for category, relation_name in rows:
        if category in listing:
            listing[category].append(relation_name)

    return {category: names for category, names in listing.items() if names}

def exec_drop(expr):
    """Remove the saved result from the list of available tables."""

    table = expr.get("table")

    # if flagged to drop all, clear the saved results
    if isinstance(table, bool) and table:
        saved_results.clear()
        print("Successfully dropped all saved tables.")
        return

    # ensure that the table is not a table from the SQL connection
    if check_sql_for_table(table_name=table):
        raise RacException("Cannot drop table from SQL connection.")

    # if the table cannot be removed or does not exist, error
    if not saved_results.pop(table, None):
        raise TableNotFoundError(table)

    print(f"Successfully dropped table: {table}")

## ~~~~~~~~ UNARY OPERATIONS ~~~~~~~~ ##

def exec_projection(expr, ndf):
    """Execute a projection operation on the given DataFrame."""

    df = ndf.df
    keep_dups = expr.get("keep_dups", False)
    attributes = process_attributes(df, expr["attributes"])

    result_df = df[attributes]

    # handle duplicates if necessary
    if not keep_dups:
        result_df = result_df.drop_duplicates()

    return NamedDataFrame(expr['table_alias'], result_df)

def exec_selection(expr, ndf):
    """Execute the given selection operation on the given DataFrame."""

    df = ndf.df
    cond = expr["condition"]
    mask = evaluate_comparison_cond(df, cond)

    if isinstance(mask, bool):
        # if the condition is a boolean, return the original DataFrame
        mask = pd.Series(mask, index=df.index)

    return NamedDataFrame(expr['table_alias'], df[mask])

def exec_group(expr, ndf):
    """Execute the given group operation on the given DataFrame."""

    df = ndf.df
    group_attrs = process_attributes(df, expr["attributes"])
    aggr_funcs = parse_aggr_conds(expr["aggr_cond"], df)

    # if not given any grouping attributes, aggregate over the whole table
    if not group_attrs:
        result_df = exec_agg_without_group(df, aggr_funcs)
        return NamedDataFrame(expr['table_alias'], result_df)

    group_df = df.groupby(group_attrs, sort=False)

    # construct aggregation mapping for pandas
    agg_dict = {}
    for alias, (col, func, distinct) in aggr_funcs.items():
        # when count by *, return how many rows are in each group
        if func == "size" and col == "*":
            temp_col = f"__mask_{alias}"
            if distinct:
                mask = pd.Series(True, index=df.index, dtype="boolean")
                mask = mask & (~df.duplicated(keep="first"))
            else:
                mask = pd.Series(True, index=df.index, dtype="boolean")

            df[temp_col] = mask.astype(int)
            agg_dict[alias] = pd.NamedAgg(column=temp_col, aggfunc="sum")

        elif func == "count":
            temp_col = f"__mask_{alias}"

            if distinct:
                valid_rows = ~pd.concat([df[c].isna() for c in col], axis=1).all(axis=1)
                group_cols = group_attrs + col
                mask = valid_rows & (~df[valid_rows].duplicated(subset=group_cols, keep="first"))
            else:
                # count when EITHER is not null
                mask = ~pd.concat([df[c].isna() for c in col], axis=1).all(axis=1)

            df[temp_col] = mask.astype(int)
            agg_dict[alias] = pd.NamedAgg(column=temp_col, aggfunc="sum")

        else:
            agg_func = make_agg_func(func, distinct)
            agg_dict[alias] = pd.NamedAgg(column=col, aggfunc=agg_func)

    result_df = group_df.agg(**agg_dict).reset_index()
    return NamedDataFrame(expr['table_alias'], result_df)

def exec_agg_without_group(orig_df, aggr_funcs):
    result_df = pd.DataFrame()
    for alias, (col, func, distinct) in aggr_funcs.items():
        if distinct and col != "*":
            df = orig_df.drop_duplicates(subset=col)
        elif distinct:
            df = orig_df.drop_duplicates()
        else:
            df = orig_df

        if func == "size" and col == "*":
            result = len(df)
        elif func == "count":
            mask = ~pd.concat([df[c].isna() for c in col], axis=1).all(axis=1)
            result = mask.sum()
        elif func == "sum":
            result = df[col].sum() if df[col].notna().any() else pd.NA
        elif func == "mean":
            result = df[col].mean() if df[col].notna().any() else pd.NA
        elif func == "min":
            result = df[col].min() if df[col].notna().any() else pd.NA
        elif func == "max":
            result = df[col].max() if df[col].notna().any() else pd.NA
        else:
            raise ValueError(f"Unsupported aggregation function: {func}")

        result_df[alias] = [result]
    return result_df

def make_agg_func(func, distinct=False):
    """Return a pandas aggregation function for the given operation and distinct flag."""

    def agg(x):
        values = x.drop_duplicates() if distinct else x
        if not values.notna().any():
            return pd.NA
        if func == "sum":
            return values.sum()
        elif func == "mean":
            return values.mean()
        elif func == "min":
            return values.min()
        elif func == "max":
            return values.max()
        else:
            raise ValueError(f"Unsupported aggregation function: {func}")

    return agg

def exec_remove_duplicates(expr, ndf):
    """Remove duplicates from the given DataFrame."""

    return NamedDataFrame(expr["table_alias"], ndf.df.drop_duplicates())

def exec_sort(expr, ndf):
    """Sort the DataFrame based on the given attributes."""

    df = ndf.df
    sort_attrs = expr["sort_attributes"]

    # Sort in reverse so the first listed attr has the higher sort importance.
    # Stable sorting preserves secondary-key order across later passes.
    for attr in reversed(sort_attrs):
        # ensure the attribute is a valid column in the DataFrame
        col = attr[0]
        if col not in df.columns:
            raise InvalidColumnName(col)

        na_position = "first" if attr[1] else "last"
        df = df.sort_values(
            by=col,
            ascending=attr[1],
            na_position=na_position,
            kind="mergesort"
        )

    return NamedDataFrame(expr['table_alias'], df)

def exec_limit(expr, ndf):
    """Return the first n rows of a DataFrame."""

    count = expr["count"]
    if count < 0:
        raise ValueError("Limit count cannot be negative.")

    return NamedDataFrame(expr["table_alias"], ndf.df.head(count).copy())


def exec_rename(expr, ndf, supress_rename=False):
    """Rename the table to the given alias."""

    alias = expr.get("table_alias")

    # check if the alias is in the sql database or is a saved table
    if not supress_rename and (check_sql_for_table(alias) or alias in saved_results):
        raise TableAlreadyExists(alias)

    return NamedDataFrame(alias, ndf.df)


## ~~~~~~~~ SET OPERATIONS ~~~~~~~~ ##

def exec_union(expr, df1, df2):
    """Execute the given union operation on the given DataFrames."""

    keep_dups = expr.get("keep_dups", False)

    # combine the two sets
    result_df = pd.concat([df1.df, df2.df], ignore_index=True)

    # handle duplicates if necessary
    if not keep_dups:
        result_df = result_df.drop_duplicates()

    return NamedDataFrame(expr['table_alias'], result_df)

def exec_interestion(expr, df1, df2):
    """Execute the given intersection operation on the given DataFrames."""

    keep_dups = expr.get("keep_dups", False)
    df1_dr, df2_dr = prepare_for_set_op(df1.df, df2.df, keep_dups)

    # merge the data frames and keep only the relevant columns
    inter = pd.merge(df1_dr, df2_dr, how="inner", on=None, validate="m:m")
    result_df = inter[df1.df.columns]

    return NamedDataFrame(expr['table_alias'], result_df)

def exec_difference(expr, df1, df2):
    """Execute the given difference operation on the given DataFrames."""

    keep_dups = expr.get("keep_dups", False)
    df1_dr, df2_dr = prepare_for_set_op(df1.df, df2.df, keep_dups)

    # merge the data frames and keep only the relevant columns/rows
    merged = pd.merge(df1_dr, df2_dr, how="left", on=None, validate="m:m",
                      indicator=True)
    diff = merged[merged['_merge'] == 'left_only']
    result_df = diff[df1.df.columns]

    return NamedDataFrame(expr["table_alias"], result_df)

def prepare_for_set_op(df1, df2, keep_dups=False):
    """Prepares two DataFrames for set operations by either 
    dropping duplicates or adding row counts (for bag semantics)."""

    # remove duplicates if not a bag
    if not keep_dups:
        df1_clean = df1.drop_duplicates()
        df2_clean = df2.drop_duplicates()

    # if a bag, add row counts to keep desired duplication
    else:
        def add_row_counts(df):
            '''Add row counts to the rows.'''
            return df.assign(
                _rownum=df.groupby(df.columns.tolist()).cumcount()
            )
        df1_clean = add_row_counts(df1)
        df2_clean = add_row_counts(df2)

    return df1_clean, df2_clean


## ~~~~~~~~ MERGE OPERATIONS ~~~~~~~~ ##

def strip_suffixes(col):
    # strip all trailing _L or _R occurrences
    while col.endswith(("_L", "_R")):
        col = col[:-2]
    return col

def normalize_relation_name(name):
    return str(name).lower()

def collect_relation_names(table_expr):
    """Return relation names that can legally qualify columns for an expression."""

    names = set()
    if table_expr is None:
        return names

    if isinstance(table_expr, str):
        names.add(normalize_relation_name(table_expr))
        return names

    if isinstance(table_expr, dict):
        if table_expr.get("operation") == "rename":
            alias = table_expr.get("table_alias")
            if alias:
                names.add(normalize_relation_name(alias))

        for key in ("table", "table1", "table2"):
            names.update(collect_relation_names(table_expr.get(key)))

    return names

def build_join_context(expr, ndf1, ndf2, left_cols, right_cols):
    """Build metadata used to resolve qualified join predicates."""

    left_names = collect_relation_names(expr.get("table1"))
    right_names = collect_relation_names(expr.get("table2"))
    left_names.update(collect_relation_names(getattr(ndf1, "query", None)))
    right_names.update(collect_relation_names(getattr(ndf2, "query", None)))

    if ndf1.name:
        left_names.add(normalize_relation_name(ndf1.name))
    if ndf2.name:
        right_names.add(normalize_relation_name(ndf2.name))

    return {
        "left_names": left_names,
        "right_names": right_names,
        "left_cols": set(left_cols),
        "right_cols": set(right_cols),
    }

def prepare_for_merge_op(left_df, right_df):
    """Ensure no duplicate column names between left_df and right_df.
    Adds _L or _R suffixes to duplicates, preserving any existing suffixes."""

    # grab the original columns from each table
    left_cols = left_df.columns.tolist()
    right_cols = right_df.columns.tolist()

    # remove any existing _L/_R suffixes to get the base column name
    left_bases = [strip_suffixes(c) for c in left_cols]
    right_bases = [strip_suffixes(c) for c in right_cols]

    duplicate_cols = set(left_bases) & set(right_bases)

    # for the left table, add a _L subscript for columns that have a duplicate
    for i, col in enumerate(left_bases):
        if col in duplicate_cols:
            left_cols[i] += "_L"

    # for the right table, add a _L subscript for columns that have a duplicate
    for i, col in enumerate(right_bases):
        if col in duplicate_cols:
            right_cols[i] += "_R"

    # reset the df columns to be the updated column names
    left_df.columns = left_cols
    right_df.columns = right_cols

def exec_cross(expr, ndf1, ndf2):
    """Execute the given cross operation on the given DataFrames."""

    df1 = ndf1.df
    df2 = ndf2.df
    orig_cols = df1.columns.tolist() + df2.columns.tolist()

    prepare_for_merge_op(df1, df2)
    result_df = pd.merge(df1, df2, how="cross",
                         suffixes=('_L', '_R'), validate="m:m")

    check_merge_col_names(result_df.columns, orig_cols)

    return NamedDataFrame(expr["table_alias"], result_df)

def exec_join(expr, ndf1, ndf2):
    """Execute the given join operation on the given DataFrames."""

    join_type = expr.get("join_type")
    condition = expr.get("condition")
    attributes = expr.get("attributes")
    alias = expr.get("table_alias")

    # add helper ids to the DataFrames and grab all the columns
    df1_dr = ndf1.df.reset_index().rename(columns={'index': '_left_id'})
    df2_dr = ndf2.df.reset_index().rename(columns={'index': '_right_id'})
    orig_cols = df1_dr.columns.tolist() + df2_dr.columns.tolist() + ['_merge']

    # if no condition, use pandas specialized merge function
    if not condition:
        merge_how = 'inner' if 'semi' in join_type else join_type
        attributes = attributes or list(set(df1_dr.columns) & set(df2_dr.columns))

        # if an inner or semi join, drop rows with nulls in the join attributes
        if merge_how == "inner":
            df1_dr = df1_dr.dropna(subset=attributes)
            df2_dr = df2_dr.dropna(subset=attributes)

        result, left_cols, right_cols = merge_and_get_cols(
            df1_dr, df2_dr, merge_how, attributes)

        # if an outer join, handle the case where nulls match
        if merge_how != "inner":
            result = fix_null_matches(result, merge_how, df1_dr, df2_dr, attributes)

    # otherwise, if a condition is specified, manually do a cross join and then filter
    else:
        merge, left_cols, right_cols = merge_and_get_cols(df1_dr, df2_dr, 'cross')

        # evaulate the condition to get a mask of the wanted rows
        join_context = build_join_context(expr, ndf1, ndf2, left_cols, right_cols)
        mask = evaluate_comparison_cond(merge, condition, join_context=join_context)
        if isinstance(mask, bool):
            mask = pd.Series(condition, index=merge.index)

        result = merge[mask]

    # get the desired output columns if a semi join, otherwise check for duplicate names
    if "semi" in join_type:
        result = get_semi_join_side(result, join_type, left_cols, right_cols)
    else:
        check_merge_col_names(result.columns, orig_cols)

    # if a specialized pandas merge or is not an outer join, return the cleaned result
    if not condition or "inner" in join_type or "semi" in join_type:
        return clean_join_result(alias, result)

    outer_result =  handle_outer_join(result, merge, join_type, left_cols, right_cols)
    return clean_join_result(alias, outer_result)

def merge_and_get_cols(df1_dr, df2_dr, merge_how, attributes=None):
    if attributes is not None and len(attributes) == 0:
        raise ValueError("No common attributes found between tables.")

    if attributes is None:
        prepare_for_merge_op(df1_dr, df2_dr)

    merge = pd.merge(df1_dr, df2_dr, how=merge_how, on=attributes,
                         suffixes=('_L', '_R'), validate="m:m", indicator=True)

    # get the columns that are from the left and the right dataframes after the join
    left_cols = [c for c in merge.columns if (c in df1_dr.columns or c.endswith('_L'))]
    right_cols = [c for c in merge.columns if (c in df2_dr.columns or c.endswith('_R'))]

    return merge, left_cols, right_cols

def fix_null_matches(merge, merge_how, df1, df2, attributes):
    null_key_match_mask = (merge["_merge"] == "both") & merge[attributes].isna().any(axis=1)
    rows_to_split = merge.loc[null_key_match_mask]

    if rows_to_split.empty:
        return merge.drop(columns=["_merge"])

    left_cols = df1.columns.tolist()
    right_cols = df2.columns.tolist()
    left_rows = rows_to_split.drop_duplicates("_left_id")
    right_rows = rows_to_split.drop_duplicates("_right_id")

    new_rows = []
    if merge_how in ("outer", "left"):
        for _, r in left_rows.iterrows():
            new_rows.append(nullify_side(r, right_cols, attributes, "_right_id"))

    if merge_how in ("outer", "right"):
        for _, r in right_rows.iterrows():
            new_rows.append(nullify_side(r, left_cols, attributes, "_left_id"))

    merge = merge.loc[~null_key_match_mask].copy()
    merge = pd.concat([merge, pd.DataFrame(new_rows)], ignore_index=True)

    return merge.drop(columns=["_merge"])

def nullify_side(row, cols, attributes, id_col):
    copy = row.copy()
    for c in cols:
        if c not in attributes:
            copy[c] = pd.NA
    if id_col in row.index:
        copy[id_col] = pd.NA
    return copy

def get_semi_join_side(merge, join_type, left_cols, right_cols):
    if "left" in join_type:
        result_df = (
            merge[left_cols].rename(columns=lambda x: x.replace('_L', ''))
                .drop_duplicates('_left_id')
        )
    else:
        result_df = (
            merge[right_cols].rename(columns=lambda x: x.replace('_R', ''))
                .drop_duplicates('_right_id')
        )
    return result_df

def check_merge_col_names(merged_cols, original_cols):
    """Check if the merged columns are the same columns as the original columns."""

    if set(merged_cols) != set(original_cols):
        print_warning("Duplicate columns found in result. " \
                      "Can cause unexpected results. " \
                      "Please ensure unique column names across tables.",
                      "JoinWarning")

def handle_outer_join(masked, merge, join_type, left_cols, right_cols):
    """Handle outer join output. Fill unmatched rows with NaN."""

    # get the original rows that matched at least once
    matched_left = set(masked['_left_id'])
    matched_right = set(masked['_right_id'])

    # get the rows that do not have a match from the left and right DataFrames
    left_only = (
        merge.loc[~merge['_left_id'].isin(matched_left), left_cols]
            .drop_duplicates('_left_id')
            .copy()
    )
    right_only = (
        merge.loc[~merge['_right_id'].isin(matched_right), right_cols]
            .drop_duplicates('_right_id')
            .copy()
    )

    # fill the unmatched rows with NaN values for the other side
    for rc in right_cols:
        left_only[rc] = pd.NA

    for lc in left_cols:
        right_only[lc] = pd.NA

    if "left" in join_type:
        parts = [masked, left_only]
    elif "right" in join_type:
        parts = [masked, right_only]
    elif "outer" in join_type:
        parts = [masked, left_only, right_only]
    else:
        raise ValueError("Invalid join type given.")

    # align and combine
    out = pd.concat(parts, ignore_index=True)
    out = out.convert_dtypes()

    if "left" in join_type:
        out = out.sort_values(by='_left_id')
    elif "right" in join_type:
        out = out.sort_values(by='_right_id')

    return out

def clean_join_result(alias, result_df):
    """Clean up the join result by dropping helper columns and resetting index."""

    # drop helper ids
    if '_left_id' in result_df.columns:
        result_df = result_df.drop(columns=['_left_id'])
    if '_right_id' in result_df.columns:
        result_df = result_df.drop(columns=['_right_id'])
    if '_merge' in result_df.columns:
        result_df = result_df.drop(columns=['_merge'])

    # reset the index
    result_df.reset_index(drop=True, inplace=True)
    result_df = result_df.convert_dtypes()

    return NamedDataFrame(alias, result_df)

def exec_divide(expr, ndf1, ndf2):
    """Execute the given divide operation on the given DataFrames."""

    df1 = ndf1.df.drop_duplicates()
    df2 = ndf2.df.drop_duplicates()

    # divisor columns and columns separate from the divisors
    divisor_cols = df2.columns.tolist()
    remaining_cols = [col for col in df1.columns if col not in divisor_cols]

    # ensure df2 columns are subset of df1
    if not set(divisor_cols).issubset(set(df1.columns)):
        raise ValueError("All columns in divisor must exist in dividend.")

    # get all combinations of the canidates with the divisors
    candidates = df1[remaining_cols].drop_duplicates()
    cross = candidates.merge(df2, how='cross')

    # find which tuples in df1 match the candidate combinations
    matched = df1.merge(cross)

    # count how many divisor matches per candidate group
    grouped = matched.groupby(remaining_cols, sort=False)
    full_matches = grouped.size().reset_index(name='_count')

    # only keep those with a full match to all df2 rows
    result_df = (full_matches[full_matches['_count'] == len(df2)])[remaining_cols]

    return NamedDataFrame(expr["table_alias"], result_df)


## ~~~~~~~~ TABLES, ATTRIBUTES, & OTHER ~~~~~~~~ ##

def get_qualified_side(qualifier, join_context):
    """Return the join side for a table qualifier, or None if ambiguous."""

    if not qualifier or not join_context:
        return None

    qualifier = normalize_relation_name(qualifier)
    left_match = qualifier in join_context.get("left_names", set())
    right_match = qualifier in join_context.get("right_names", set())

    if left_match and not right_match:
        return "left"
    if right_match and not left_match:
        return "right"
    return None

def resolve_column_from_side(df, col_name, side, join_context):
    suffix = "_L" if side == "left" else "_R"
    side_cols = join_context.get(f"{side}_cols", set())

    for candidate in (f"{col_name}{suffix}", col_name):
        if candidate in side_cols and candidate in df.columns:
            return df[candidate]

    raise InvalidColumnName(col_name)

def resolve_operand(df, operand, left=True, join_context=None):
    """Resolve a column reference, literal, or math expression into a value or Series."""

    try:

        # evaltuate math or comp conditions
        if isinstance(operand, dict):
            t = operand.get("type")
            if t == "math_cond":
                return evaluate_math_cond(df, operand, join_context=join_context)

            if t == "date_part":
                return evaluate_date_part(df, operand, join_context=join_context)

            if t == "comp_cond":
                return evaluate_comparison_cond(df, operand, join_context=join_context)
            if t == "alias":
                alias = operand["alias"]
                df[alias] = resolve_operand(df, operand["attr"], join_context=join_context)
                return df[alias]

            raise ValueError(f"Unknown operand type: {t}")

        # resolve table.attr names
        if isinstance(operand, list):
            qualifier = operand[0] if len(operand) > 1 else None
            col_name = operand[-1]
            qualified_side = get_qualified_side(qualifier, join_context)
            if qualified_side:
                return resolve_column_from_side(df, col_name, qualified_side, join_context)

            join_name = col_name + "_L" if left else col_name + "_R"
            if col_name in df:
                return df[col_name]

            if join_name in df:
                return df[join_name]

        if isinstance(operand, str):
            # if a string wrapped in "", assume a string literal
            if ((operand.startswith('"') and operand.endswith('"'))
                or (operand.startswith("'") and operand.endswith("'"))):
                return operand.strip('"\'')

            # if a string is a column name, return the column
            if left:
                suffix = "_L"
            else:
                suffix = "_R"

            for col in df.columns:
                if (col == operand or (
                    (col.endswith(suffix)) and (strip_suffixes(col) == operand))):
                    return df[col]

        # if a number, just return
        return operand

    except KeyError as e:
        raise InvalidColumnName(e.args[0]) from e

def evaluate_math_cond(df, expr, join_context=None):
    """Evaluate a math expression with the given df."""
    left = resolve_operand(df, expr["left"], join_context=join_context)
    right = resolve_operand(df, expr["right"], left=False, join_context=join_context)
    op = expr["op"]

    match op:
        case "+":
            return left + right
        case "-":
            return left - right
        case "*":
            return left * right
        case "/":
            return left / right
        case "%":
            return left % right
        case "^":
            return left ** right
        case _:
            raise ValueError(f"Unsupported math operator: {op}")

def format_attr_label(attr):
    """Return a readable label for an attribute expression."""

    if isinstance(attr, list):
        return ".".join(str(part) for part in attr)
    return str(attr)


def date_part_alias(expr):
    """Return the default output column for a date-part expression."""

    attr_name = format_attr_label(expr["attr"]).replace(".", "_")
    return f"{expr['func'].lower()}_{attr_name}"


def evaluate_date_part(df, expr, join_context=None):
    """Evaluate month(...) or year(...) for a date-like attribute."""

    func = expr["func"].lower()
    source = resolve_operand(df, expr["attr"], join_context=join_context)
    if not isinstance(source, pd.Series):
        raise InvalidColumnName(format_attr_label(expr["attr"]))

    if pd.api.types.is_numeric_dtype(source):
        raise ValueError(f"{func}() can only be used with date-like attributes.")

    try:
        dates = pd.to_datetime(source, errors="coerce")
    except (TypeError, ValueError) as e:
        raise ValueError(f"{func}() can only be used with date-like attributes.") from e

    invalid_dates = source.notna() & dates.isna()
    if invalid_dates.any():
        raise ValueError(f"{func}() can only be used with date-like attributes.")

    if func == "month":
        result = dates.dt.month
    elif func == "year":
        result = dates.dt.year
    else:
        raise ValueError(f"Unsupported date function: {func}")

    return result.astype("Int64")


def evaluate_comparison_cond(df, cond, join_context=None):
    """Recursively evaluate a comparison or logical condition."""

    # if the condition is a boolean, return a full/empty mask
    if isinstance(cond, bool):
        return pd.Series(cond, index=df.index, dtype="boolean")

    # recursive and/or condition
    if cond["op"] in {"AND", "OR"}:
        left_mask = evaluate_comparison_cond(df, cond["left"], join_context=join_context)
        right_mask = evaluate_comparison_cond(df, cond["right"], join_context=join_context)

        if cond["op"] == "AND":
            return left_mask & right_mask
        else:
            return left_mask | right_mask

    # binary comparison operator
    left_val = resolve_operand(df, cond["left"], join_context=join_context)
    right_val = resolve_operand(df, cond["right"], left=False, join_context=join_context)
    op = cond["op"]

    if not isinstance(left_val, pd.Series):
        left_val = pd.Series([left_val] * len(df), index=df.index)
    if not isinstance(right_val, pd.Series):
        right_val = pd.Series([right_val] * len(df), index=df.index)

    # get which rows have NA's
    if not isinstance(left_val, pd.Series):
        left_val = pd.Series([left_val] * len(df), index=df.index)
    if not isinstance(right_val, pd.Series):
        right_val = pd.Series([right_val] * len(df), index=df.index)

    na_mask = left_val.isna() | right_val.isna()
    non_na_idx = ~na_mask

    # default rows with NA's to False
    result = pd.Series(False, index=df.index, dtype='boolean')

    if op == ">":
        result[non_na_idx] = left_val[non_na_idx] > right_val[non_na_idx]
    elif op == "<":
        result[non_na_idx] = left_val[non_na_idx] < right_val[non_na_idx]
    elif op in {"=", "=="}:
        result[non_na_idx] = left_val[non_na_idx] == right_val[non_na_idx]
    elif op == ">=":
        result[non_na_idx] = left_val[non_na_idx] >= right_val[non_na_idx]
    elif op == "<=":
        result[non_na_idx] = left_val[non_na_idx] <= right_val[non_na_idx]
    elif op == "!=":
        result[non_na_idx] = left_val[non_na_idx] != right_val[non_na_idx]
    else:
        raise ValueError(f"Unsupported comparison operator: {op}")

    return result

def process_attributes(df, attributes_expr):
    """
    Process a list of attribute expressions, modifying the DataFrame in place
    to include any computed columns, and returning a list of column names.

    Args:
        df (pd.DataFrame): the dataframe to operate on
        attributes_expr (list): list of attributes (strings, lists, or dicts)

    Returns:
        list: list of column names (including computed ones)
    """
    processed_attrs = []

    for attr in attributes_expr:
        if isinstance(attr, dict):
            # compute an aliased column
            if attr.get("type") == "date_part":
                alias = attr.get("alias") or date_part_alias(attr)
                df[alias] = evaluate_date_part(df, attr)
            else:
                alias = attr["alias"]
                if "cond" in attr:
                    df[alias] = evaluate_math_cond(df, attr["cond"])
                elif "attr" in attr:
                    df[alias] = resolve_operand(df, attr["attr"])
            processed_attrs.append(alias)
        elif isinstance(attr, list):
            # handle a dotted column name
            processed_attrs.append(attr[-1])
        else:
            if attr == "*":
                # if the attribute is *, return all columns
                processed_attrs = df.columns.tolist()
            else:
                # otherwise, just add the column name
                processed_attrs.append(attr)

    return processed_attrs

def parse_aggr_conds(aggr_conds, df):
    """Convert aggr_cond expressions into a dict of output_column -> (col, agg_func)"""

    aggr_funcs = {}
    for aggr in aggr_conds:
        # grab the alias if given one
        if isinstance(aggr, list):
            alias = aggr[1]
            aggr = aggr[0]
        else:
            alias = None

        op = aggr["aggr"].lower()
        attr = aggr.get("attr", ["*"])
        attrs = process_attributes(df, attr)
        distinct = aggr.get("distinct", False)
        distinct_alias = "_^d" if distinct else ""

        # Special handling for count(*)
        if op == "count" and attr == ["*"]:
            alias = alias if alias else f"count_star{distinct_alias}"
            aggr_funcs[alias] = ("*", "size", distinct)
        elif op == "count":
            alias = alias if alias else f"count_{'_'.join(attrs)}{distinct_alias}"
            aggr_funcs[alias] = (attrs, op, distinct)
        else:
            alias = alias if alias else f"{op}_{'_'.join(attrs)}{distinct_alias}"
            aggr_funcs[alias] = (attrs[0], op, distinct)

    return aggr_funcs
