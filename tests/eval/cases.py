"""Evaluation cases for the seeded SQLite e-commerce schema.

These cases target the schema produced by ``docker/sqlite/init.sql`` (and the
project's ``data.db``): ``products``, ``customers`` and ``orders``. Both
``expected_sql`` and ``expected_rows`` are given where deterministic.
"""

from __future__ import annotations

from tests.eval.evaluator import EvalCase


def load_default_cases() -> list[EvalCase]:
    """Return the default evaluation case suite.

    Returns:
        A list of EvalCase objects.
    """
    return [
        EvalCase(
            id="product_count",
            question="How many products are there in total?",
            expected_sql="SELECT COUNT(*) AS total FROM products",
            expected_rows=1,
        ),
        EvalCase(
            id="product_names",
            question="List the names of all products.",
            expected_sql="SELECT name FROM products ORDER BY name",
            expected_rows=6,
        ),
        EvalCase(
            id="us_customers",
            question="How many customers are located in the US?",
            expected_sql="SELECT COUNT(*) FROM customers WHERE country = 'US'",
            expected_rows=1,
        ),
        EvalCase(
            id="electronics_products",
            question="Which products belong to the electronics category?",
            expected_sql="SELECT name FROM products WHERE category = 'electronics' ORDER BY name",
            expected_rows=4,
        ),
        EvalCase(
            id="top_expensive",
            question="What are the 3 most expensive products?",
            expected_sql="SELECT name, price FROM products ORDER BY price DESC LIMIT 3",
            expected_rows=3,
        ),
        EvalCase(
            id="pending_orders",
            question="How many orders are currently pending?",
            expected_sql="SELECT COUNT(*) FROM orders WHERE status = 'pending'",
            expected_rows=1,
        ),
        EvalCase(
            id="total_completed_orders",
            question="How many completed orders are there in total?",
            expected_sql="SELECT COUNT(*) FROM orders WHERE status = 'completed'",
            expected_rows=6,
        ),
        EvalCase(
            id="orders_per_customer",
            question="How many unique customers have placed at least one order?",
            expected_sql="SELECT COUNT(DISTINCT customer_id) FROM orders",
            expected_rows=1,
        ),
        EvalCase(
            id="revenue_by_category",
            question="Show the total revenue for each product category based on order quantity and unit price.",
            expected_sql=(
                "SELECT products.category, SUM(orders.quantity * orders.unit_price) AS revenue "
                "FROM orders JOIN products ON orders.product_id = products.id "
                "GROUP BY products.category"
            ),
            expected_rows=2,
        ),
    ]