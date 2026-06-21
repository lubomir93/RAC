# tests/_base.py
"""Setup and Teardown methods for setting up DB tables for testing."""

import unittest
import ra_compiler.mysql as db

class BaseTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        db.setup_mysql()

        cls.CONN = getattr(db, "CONN", getattr(db, "connection", None))
        if cls.CONN is None:
            raise unittest.SkipTest("No DB connection available")

        cur = cls.CONN.cursor()

        # Prepare testTable
        cur.execute("DROP TABLE IF EXISTS testTable;")
        cur.execute("CREATE TABLE testTable (a INT, b INT, tdate DATE);")
        cur.executemany("INSERT INTO testTable (a, b, tdate) VALUES (%s, %s, %s);",
                        [
                            (0, 1, "2024-01-15"),
                            (1, 2, "2024-02-20"),
                            (2, 2, "2025-02-28"),
                            (4, 3, "2025-12-01"),
                        ])

        # Prepare testTabR table
        cur.execute("DROP TABLE IF EXISTS testTabR;")
        cur.execute("""CREATE TABLE testTabR
                    (age INT, b INT, c INT, d INT, name VARCHAR(50));""")
        rac_rows = [
            (12, 5, 19, 4, "alice"),
            (7, 15, 2, 17, "bob"),
            (11, 20, 8, 6, "claire"),
            (3, 18, 9, 10, "dave"),
            (14, 7, 1, 13, "emma"),
            (8, 16, 5, 12, "faith"),
            (19, 6, 17, 2, "george"),
            (4, 10, 11, 3, "hannah"),
            (1, 13, 14, 9, "ian"),
            (1, 13, 14, 9, "jack"),
            (6, 3, 20, 15, "kelly"),
            (6, 3, 20, 15, "kelly"),
            (8, 3, 9, 4, "bob"),
            (8, 4, 9, 4, "bob"),
            (8, 5, 9, 4, "bob"),
            (12, None, 3, None, None),
        ]
        cur.executemany("INSERT INTO testTabR VALUES (%s, %s, %s, %s, %s)", rac_rows)

        # Prepare T table
        cur.execute("DROP TABLE IF EXISTS T;")
        cur.execute("""CREATE TABLE T (age INT, b INT, c INT);""")
        t_rows = [
            (1, 3, 100),
            (3, 4, 200),
            (6, 5, 300),
            (12, 6, 400),
        ]
        cur.executemany("INSERT INTO T VALUES (%s, %s, %s)", t_rows)

        cls.CONN.commit()
        cur.close()

    @classmethod
    def tearDownClass(cls):
        # Clean up testTable
        if cls.CONN:
            cur = cls.CONN.cursor()
            cur.execute("DROP TABLE IF EXISTS testTable;")
            cur.execute("DROP TABLE IF EXISTS testTabR;")
            cur.execute("DROP TABLE IF EXISTS T;")
            cls.CONN.commit()
            cur.close()

        db.close_mysql()
