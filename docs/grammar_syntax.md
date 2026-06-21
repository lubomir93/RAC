# Relational Algebra Interpreter Syntax

## Overview

This is a **relational algebra–focused** language for expressing queries over relational tables. All expressions must be wrapped in parentheses.

- `{}` is used to enclose **subscripts**, such as attribute lists or conditions.
- The `^d` suffix on operations (e.g., `\pi^d`, `\union^d`) indicates **bag semantics**, meaning duplicates are preserved rather than removed.
- Multiple aliases are supported for many operations to accommodate different styles (e.g., `\sigma`, `\selection`, `\select` all perform selection).
- Keywords are not case sensitive.
- Queries can be nested by placing one expression inside another: `(\pi{...} (\selection{...} Table))`


## Supported Operations

- Database Operations:
    - [List](#list)
    - [Drop](#drop)
- Unary Operations:
    - [Projection](#projection)
    - [Selection](#selection)
    - [Group By/Aggregation](#group-by-and-aggregation)
    - [Remove Duplicates](#remove-duplicates)
    - [Sort](#sort)
    - [Limit](#limit)
    - [Rename](#rename)
- Set Operations:
    - [Union](#union)
    - [Intersection](#intersection)
    - [Difference](#difference)
- Merge Operations:
    - [Cross Product](#cross-product)
    - [Joins](#joins)
    - [Divide](#divide)

<br>

**Notes on Operation Types**

- Database operations: functions to help manage saved virtual views and available tables.
- Unary operations: operate on a **single table**.
- Set operations: combine **two tables with the same schema**.
- Merge operations: combine **two tables**, typically on related keys or conditions.

---

## Database Operations

### List

Shows available database relations and RAC virtual views that can be used in expressions.

**Valid Keywords Variations**: `\list`, `list`

**Syntax options**:
```
list
\list
```

**Explanation**:
- Returns non-empty categories only.
- PostgreSQL listings include visible tables, temporary tables, virtual views, materialized views, and RAC virtual views.
- MySQL listings include tables, views, and RAC virtual views.
- Unnamed query results such as _rac_q2 are displayed once but are not saved or listed.
- Useful to check which relations are accessible at any point.

---

### Drop

Removes a virtual view from the available list of relations. Can be used to discard saved virtual views or free memory.

**Valid Keywords Variations**: `\drop`

**Syntax options**:
```
(\drop StudentsView)
(\drop RecentStudents)
(\drop -all)
```

**Explanation**:
- Deletes the specified virtual view from the working set.
- After dropping, the virtual view will no longer appear in `\list`.
- This does not delete the original tables from the SQL database, only the virtual views created during the session.
- `-all` can be used to remove all saved virtual views.

---

## Unary Operations

### Projection

Selects specific attributes, optionally renaming them or computing derived values. Supports bag semantics (^d).

**Valid Keywords Variations**:
- set semantics: `\projection`, `\pi`
- bag semantics: `\projection^d`, `\pi^d`

**Syntax options**:
```
(\pi{name, age} Students)
(\projection{name, age} Students)
(\pi^d{name, age} Students)         ; keeps duplicates
(\pi{name + 2 -> agePlus2} Students)
(\pi{month(enrolledOn), year(enrolledOn) -> enrolledYear} Students)
(\projection{name -> fullName} Students)
```

**Explanation**:
- Returns a table with only the specified attributes.
- `->` can be used to rename attributes or give aliases to expressions.
- `month(date_attr)` and `year(date_attr)` can be used to project date parts. Without `->`, output columns use names like `month_tdate`.
- `^d` means **"don't remove duplicates"**, i.e., use bag semantics instead of set semantics.

---

### Selection

Filters rows based on a condition.

**Valid Keywords Variations**: `\selection`, `\select`, `\sigma`

**Syntax options**:
```
(\sigma {age > 30} Students)
(\selection{age > 30 and gpa=4.0} Students)
(\select{name = "Alice"} Employees)
```

**Explanation**:
- Keeps only the rows from the input table that satisfy the given condition.
- If the condition evaluates to True, it will return every row. Similarly, if the condition evaluates to False, it will return no rows.

---

### Group By and Aggregation

Groups rows by one or more attributes and applies aggregate functions (e.g., `sum`, `count`, `avg`, etc.).

**Valid Keywords Variations**: `\group_by`, `\group`, `\gamma`

**Syntax options**:
```
(\group{dept; count(*), avg(salary)} Employees)
(\group_by{name; sum(score)} Results)
(\gamma{category; max(price) -> top_price} Products)
(\gamma{category; max(price), avg(distinct price)} Products)
```

**Explanation**:
- The part before the `;` specifies the group-by attributes.
- The part after the `;` contains aggregation expressions.
- Aggregates can include `count`, `sum`, `avg`, `min`, and `max`.
    - `count(*)` can be used to count all unique grouped-by rows
    - `distinct` can be used to only include unique values per aggregate
    - `->` can be used after an aggregate to rename the resulting column

---

### Remove Duplicates

Removes duplicate rows from a relation.

**Valid Keywords Variations**: `\remove_duplicates`, `\remove_dups`, `\delta`

**Syntax options**:
```
(\remove_duplicates Students)
(\remove_dups (\pi{name} Employees))
(\delta (\projection{name} Employees))
```

**Explanation**: Enforces set semantics explicitly by discarding repeated rows.

---

### Sort

Sorts rows by specified attributes in ascending or descending order.

**Valid Keywords Variations**: `\sort`, `\order`, `\tau`

**Syntax options**:
```
(\sort{name asc} Students)
(\order{dept desc, age asc} Employees)
(\tau{salary desc} Employees)
```

**Explanation**: Orders the rows based on one or more attributes and directions. Valid directions are `asc` (ascending) and `desc` (descending).

---

### Limit

Returns the first n rows from a relation.

**Valid Keywords Variations**: `\limit`

**Syntax options**:
```
(\limit{10} Students)
(\limit{5} (\sort{age desc} Students))
```

**Explanation**: Keeps the current row order and returns the first n tuples. It can be composed after sort to retrieve top-n rows.

---

### Rename

Creates a temporary virtual view of the query.

**Valid Keywords Variations**: `\rename`, `\rho`

**Syntax options**:
```
(\rename (RenamedTable, Students))
(\rho (X, (\selection{age > 20} Students)))
```

**Explanation**: Creates a temporary virtual view of the query to use in further operations. Will store the query, rather than the table itself, so changes made to the tables used in the queries will reflect in the virtual view. All saved virtual views will be wiped at the end of the session.

---

## Set Operations

### Union

Combines rows from two relations. Supports bag semantics (^d).

**Valid Keywords Variations**:
- set semantics: `\union`, `\u`
- bag semantics: `\union^d`, `\u^d`

**Syntax options**:
```
(Students \union Graduates)
(Students \u^d Alumni)
```

**Explanation**:
- Combines all rows from both inputs.
- `\union` removes duplicates (set semantics).
- `\union^d` keeps duplicates (bag semantics).

---

### Intersection

Returns only the rows that appear in **both** relations. Supports bag semantics (^d).

**Valid Keywords Variations**:
- set semantics: `\intersect`, `\inter`
- bag semantics: `\intersect^d`, `\inter^d`

**Syntax options**:
```
(Students \inter Graduates)
(Employees \intersect^d Contractors)
```

**Explanation**:
- Keeps rows that appear in **both** inputs.
- `^d` variant preserves the frequency from the inputs.

---

### Difference

Returns rows in the first relation that **do not appear** in the second. Supports bag semantics (^d).

**Valid Keywords Variations**:
- set semantics: `\difference`, `\diff`, `\subtract`
- bag semantics: `\difference^d`, `\diff^d`, `\subtract^d`

**Syntax options**:
```
(Students \diff Dropouts)
(Employees \difference^d FormerEmployees)
```

**Explanation**:
- Performs set subtraction.
- `^d` variant uses bag-based subtraction.

---

## Merge Operations

### Cross Product

Produces the Cartesian product of two relations.

**Valid Keywords Variations**: `\cross_product`, `\cross`, `\x`

**Syntax options**:
```
(Students \x Courses)
(Employees \cross_product Departments)
```

**Explanation**: Every row in the first relation is paired with every row in the second.

---

### Joins

Combines rows from two tables based on a condition or join type.

**Valid Keywords Variations**:
- Inner Join:
    - `\j`, `\join`
    - `\inner`, `\inner_j`, `\inner_join`

- Inner\Semi Left Join:
    - `\semi`, `\semi_j`, `\semi_join`
    - `\left_semi`, `\left_semi_j`, `\left_semi_join`

- Inner\Semi Right Join:
    - `\right_semi`, `\right_semi_j`, `\right_semi_join`

- Full Outer Join:
    - `\full`, `\full_j`, `\full_join`
    - `\full_outer`, `\full_outer_j`, `\full_outer_join`
    - `\outer`, `\outer_j`, `\outer_join`

- Left Outer Join:
    - `\left`, `\left_j`, `\left_join`
    - `\left_outer`, `\left_outer_j`, `\left_outer_join`

- Right Outer Join
    - `\right`, `\right_j`, `\right_join`
    - `\right_outer`, `\right_outer_j`, `\right_outer_join`


**Syntax options**:
```
(Students \join{name = advisor} Professors)
(Students \inner_join Professors)
(Students \left_join Professors)
(Students \right_outer{name = id} Advisors)
(Students \semi{name = advisor} Professors)
```

**Supported Join Types**:
- Inner Join
- Left/Right Semi Joins
- Full Outer Join
- Left/Right Outer Joins


**Explanation**:
- Can be used with or without join conditions.
- Conditions go inside `{}` (e.g., `{Students.name = Professors.advisor}`).
- Semi-joins return rows only from the left table that match the condition.

---

### Divide

Implements relational division: useful for queries like "Find students who are enrolled in **all** courses".

**Valid Keywords Variations**: `\divide`, `\div`

**Syntax options**:
```
(Enrolled \divide Courses)
(Enrollment \div RequiredCourses)
```

**Explanation**: Returns rows from the first table that are associated with **all** rows in the second.

---

## Example Combined Expression

```
(\pi{name, avgSalary}
  (\group{dept; avg(salary) -> avgSalary}
    (\selection{age > 30} Employees)))
```

**Explanation**:
- Filters employees older than 30.
- Groups them by department.
- Computes the average salary per department.
- Projects just the name and computed average salary (aliased as `avgSalary`).
