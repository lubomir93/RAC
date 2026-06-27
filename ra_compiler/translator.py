# ra_compiler/translator.py
'''Translate the Lark parsed Tree into a dict.'''

from lark import Transformer
from .utils import print_debug

class RATranslator(Transformer):
    """Transforms a Lark parse tree into a relational algebra representation."""

    def __init__(self, query_count):
        super().__init__()
        self.query_count = query_count

    def _new_alias(self):
        alias = f"_rac_q{self.query_count}"
        return alias

    def add_alias(self, expr):
        if "table_alias" not in expr:
            expr["table_alias"] = self._new_alias()
        return expr

    dup_indicator = "^d"

    def start(self, items):
        if len(items) > 1:
            return self.unary_ops([self.rename(reversed(items))])
        return items[0]


    ## ~~~~~~~~ DATABASE OPERATIONS ~~~~~~~~ ##

    def db_ops(self, items):
        return { "op_type": "db"} | items[0]

    def list(self, _):
        return {
            "operation": "list",
        }

    def drop(self, items):
        return {
            "operation": "drop",
            "table": items[0]
        }

    ## ~~~~~~~~ UNARY OPERATIONS ~~~~~~~~ ##

    def unary_ops(self, items):
        return { "op_type": "unary"} | items[0]

    def projection(self, items):
        prefix, attributes, table = items

        return self.add_alias({
            "operation": "projection",
            "keep_dups": self.dup_indicator in prefix.value,
            "table": table,
            "attributes": attributes,
        })

    def selection(self, items):
        condition, table = items

        return self.add_alias({
            "operation": "selection",
            "table": table,
            "condition": condition,
        })

    def group(self, items):
        if len(items) == 2:
            attributes = []
            aggr_cond, table = items
        else:
            attributes, aggr_cond, table = items

        return self.add_alias({
            "operation": "group",
            "table": table,
            "attributes": attributes,
            "aggr_cond": aggr_cond,
        })

    def remove_duplicates(self, items):
        table = items[0]
        return self.add_alias({
            "operation": "remove_duplicates",
            "table": table,
        })

    def sort(self, items):
        sort_attributes, table = items
        return self.add_alias({
            "operation": "sort",
            "table": table,
            "sort_attributes": sort_attributes,
        })

    def limit(self, items):
        count, table = items
        return self.add_alias({
            "operation": "limit",
            "table": table,
            "count": count,
        })

    def rename(self, items):
        cname, table = items
        return {
            "operation": "rename",
            "table": table,
            "table_alias": cname,
        }

    ## ~~~~~~~~ SET OPERATIONS ~~~~~~~~ ##

    def set_ops(self, items):
        return { "op_type": "set"} | items[0]

    def union(self, items):
        table1, prefix, table2 = items
        return self.add_alias({
            "operation": "union",
            "keep_dups": True if self.dup_indicator in prefix.value else False,
            "table1": table1,
            "table2": table2,
        })

    def intersection(self, items):
        table1, prefix, table2 = items
        return self.add_alias({
            "operation": "intersection",
            "keep_dups": True if self.dup_indicator in prefix.value else False,
            "table1": table1,
            "table2": table2,
        })

    def difference(self, items):
        table1, prefix, table2 = items
        return self.add_alias({
            "operation": "difference",
            "keep_dups": True if self.dup_indicator in prefix.value else False,
            "table1": table1,
            "table2": table2,
        })

    ## ~~~~~~~~ MERGE OPERATIONS ~~~~~~~~ ##

    def merge_ops(self, items):
        return {"op_type": "merge"} | items[0]

    def cross(self, items):
        table1, table2 = items
        return self.add_alias({
            "operation": "cross",
            "table1": table1,
            "table2": table2,
        })

    def join(self, items):
        if len(items) == 3:
            table1, join_prefix, table2 = items
            specs = None
        elif len(items) == 4:
            table1, join_prefix, specs, table2 = items
        else:
            raise ValueError(f"Unexpected number of items in join: {len(items)}")

        # determine what type of join by the prefix
        def get_join_type(join_prefix):
            join = join_prefix.lstrip('/').lower()

            if "semi" in join:
                if "right" in join:
                    return "semi", "right"
                else:
                    return "semi", "left"

            if "right" in join:
                return "right"
            elif "left" in join:
                return "left"
            elif "full" in join or "outer" in join:
                return "outer"
            else:
                return "inner"

        join_dict = {
            "operation": "join",
            "join_type": get_join_type(join_prefix),
            "table1": table1,
            "table2": table2,
        }

        # deterine if given a list of attributes or a comp condition
        if isinstance(specs, list):
            join_dict["attributes"] = specs
        elif isinstance(specs, dict):
            join_dict["condition"] = specs

        return self.add_alias(join_dict)

    def divide(self, items):
        table1, table2 = items
        return self.add_alias({
            "operation": "divide",
            "table1": table1,
            "table2": table2,
        })

    ## ~~~~~~~~ TABLES, ATTRIBUTES, & OTHER ~~~~~~~~ ##

    def table(self, items):
        return items[0]

    def attributes(self, attrs):
        return attrs

    def sort_attributes(self, attrs):
        return attrs

    def attr(self, items):
        if isinstance(items[0], dict):
            expr = items[0]
            if len(items) == 1:
                return expr
            if expr.get("type") == "date_part":
                return expr | {"alias": str(items[1])}
            return {
                'alias': str(items[1]),
                'cond': expr
            }

        return items

    def alias_attr(self, items):
        return {
            'type': 'alias',
            'attr': items[0],
            'alias': str(items[1])
        }

    def sort_attr(self, items):
        return (items[0], items[1])

    def math_cond(self, items):
        if len(items) == 1:
            return items[0]

        left, op, right = items
        return {
            "type": "math_cond", 
            "left": left, 
            "op": op, 
            "right": right
        }

    def date_part_func(self, items):
        func = items[0]
        attr = items[1:]
        if len(attr) == 1:
            attr = attr[0]
        return {
            "type": "date_part",
            "func": func,
            "attr": attr
        }

    def comp_cond(self, items):
        if len(items) == 1:
            return items[0]

        left, op, right = items
        return {
            "type": "comp_cond", 
            "left": left, 
            "op": op, 
            "right": right
        }

    def aggr_conds(self, items):
        return items

    def aggr_term(self, items):
        if len(items) == 1:
            return items[0]
        elif len(items) == 2:
            return [items[0], items[1]]
        else:
            raise ValueError("Invalid aggregation condition format")

    def coalesce_func(self, items):
        return {
            "type": "coalesce",
            "args": items
        }

    def aggr_func(self, items):
        if len(items) == 2:
            aggr_op, attrs = items
            distinct = False
        else:
            aggr_op, distinct, attrs = items

        aggr_op_map = {
            "sum": "sum",
            "count": "count",
            "avg": "mean",
            "mean": "mean",
            "min": "min",
            "max": "max"
        }
        if aggr_op not in aggr_op_map:
            raise ValueError(f"Unsupported aggregation operator: {aggr_op}")

        if not isinstance(attrs, list):
            attrs = [attrs]
        return {
            "aggr": aggr_op_map[aggr_op], 
            "distinct": distinct, 
            "attr": attrs
        }

    def ALL_ATTR(self, _):
        return "*"

    def MATH_OP(self, token):
        return token.value

    def COMP_OP(self, token):
        return token.value

    def AGGR_OP(self, token):
        return token.value

    def COUNT_OP(self, token):
        return token.value

    def DATE_PART_FUNC(self, token):
        return token.value.lower()

    def AND(self, _):
        return "AND"

    def OR(self, _):
        return "OR"

    def SORT_DIR(self, token):
        return token.value.upper() == "ASC"

    def TRUTH_VAL(self, token):
        if token.value.lower() in ["true", "t"]:
            return True
        elif token.value.lower() in ["false", "f"]:
            return False
        else:
            raise ValueError(f"Invalid truth value: {token.value}")

    def NULL_LITERAL(self, _):
        return None

    def DISTINCT(self, _):
        return True

    def ALL(self, _):
        return True

    def CNAME(self, token):
        return token.value

    def NUMBER(self, token):
        return int(token.value)

    def ESCAPED_STRING(self, token):
        return token.value

    def _ambig(self, options):
        # print_debug("encountered an ambiguous parse")
        return options[0]  # pick the first ambiguous option
