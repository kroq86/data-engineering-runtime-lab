from __future__ import annotations


def print_sql_interview_queries() -> None:
    print("Top SQL interview query patterns:\n")

    print("1) Find duplicates by email")
    print(
        "SELECT email, COUNT(*) AS cnt\n"
        "FROM users\n"
        "GROUP BY email\n"
        "HAVING COUNT(*) > 1;\n"
    )

    print("2) Top 3 salaries per department")
    print(
        "WITH ranked AS (\n"
        "  SELECT department_id, employee_id, salary,\n"
        "         ROW_NUMBER() OVER (\n"
        "           PARTITION BY department_id ORDER BY salary DESC\n"
        "         ) AS rn\n"
        "  FROM employees\n"
        ")\n"
        "SELECT *\n"
        "FROM ranked\n"
        "WHERE rn <= 3;\n"
    )

    print("3) Customers with no orders")
    print(
        "SELECT c.customer_id\n"
        "FROM customers c\n"
        "LEFT JOIN orders o ON o.customer_id = c.customer_id\n"
        "WHERE o.customer_id IS NULL;\n"
    )

    print("4) Second highest salary")
    print(
        "SELECT MAX(salary) AS second_highest\n"
        "FROM employees\n"
        "WHERE salary < (SELECT MAX(salary) FROM employees);\n"
    )

    print("5) Running total by date")
    print(
        "SELECT order_date, amount,\n"
        "       SUM(amount) OVER (ORDER BY order_date) AS running_total\n"
        "FROM orders;\n"
    )

    print("6) WHERE vs HAVING example")
    print(
        "SELECT department_id, COUNT(*) AS employee_count\n"
        "FROM employees\n"
        "WHERE is_active = TRUE\n"
        "GROUP BY department_id\n"
        "HAVING COUNT(*) >= 5;\n"
    )

    print("7) ROW_NUMBER vs RANK vs DENSE_RANK")
    print(
        "SELECT employee_id, department_id, salary,\n"
        "       ROW_NUMBER() OVER (\n"
        "         PARTITION BY department_id ORDER BY salary DESC\n"
        "       ) AS row_num,\n"
        "       RANK() OVER (\n"
        "         PARTITION BY department_id ORDER BY salary DESC\n"
        "       ) AS rank_num,\n"
        "       DENSE_RANK() OVER (\n"
        "         PARTITION BY department_id ORDER BY salary DESC\n"
        "       ) AS dense_rank_num\n"
        "FROM employees;\n"
    )

    print("8) EXPLAIN ANALYZE for plan inspection")
    print(
        "EXPLAIN ANALYZE\n"
        "SELECT *\n"
        "FROM orders\n"
        "WHERE customer_id = 4242;\n"
    )
