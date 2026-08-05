-- ============================================================
-- AI SQL Agent - sample/dev schema for SQLite.
-- SQLite-compatible port of docker/postgres/init.sql so the agent
-- has an e-commerce dataset to query without needing a server.
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price       NUMERIC(10, 2) NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    country     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    product_id   INTEGER NOT NULL REFERENCES products(id),
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    unit_price   NUMERIC(10, 2) NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_product  ON orders(product_id);

-- Seed data (idempotent: only insert when empty)
INSERT INTO products (name, category, price)
SELECT name, category, price FROM (
    SELECT 'Laptop Pro 16' AS name, 'electronics' AS category, 1899.99 AS price
    UNION ALL SELECT 'Wireless Mouse', 'electronics', 49.99
    UNION ALL SELECT 'Mechanical Keyboard', 'electronics', 129.99
    UNION ALL SELECT 'USB-C Hub', 'electronics', 79.99
    UNION ALL SELECT 'Desk Lamp', 'home', 59.99
    UNION ALL SELECT 'Coffee Mug 500ml', 'home', 19.99
) WHERE NOT EXISTS (SELECT 1 FROM products);

INSERT INTO customers (email, name, country)
SELECT email, name, country FROM (
    SELECT 'alice@example.com' AS email, 'Alice Smith' AS name, 'US' AS country
    UNION ALL SELECT 'bob@example.com', 'Bob Jones', 'US'
    UNION ALL SELECT 'carol@example.com', 'Carol Nguyen', 'CA'
    UNION ALL SELECT 'dave@example.com', 'Dave Patel', 'UK'
    UNION ALL SELECT 'erin@example.com', 'Erin Garcia', 'MX'
) WHERE NOT EXISTS (SELECT 1 FROM customers);

INSERT INTO orders (customer_id, product_id, quantity, unit_price, status, created_at)
SELECT customer_id, product_id, quantity, unit_price, status, created_at FROM (
    SELECT 1 AS customer_id, 1 AS product_id, 2 AS quantity, 1899.99 AS unit_price,
           'completed' AS status, datetime('now', '-40 days') AS created_at
    UNION ALL SELECT 1, 2, 1, 49.99,  'completed', datetime('now', '-30 days')
    UNION ALL SELECT 2, 3, 1, 129.99, 'completed', datetime('now', '-25 days')
    UNION ALL SELECT 3, 4, 2, 79.99,  'shipped',   datetime('now', '-10 days')
    UNION ALL SELECT 4, 5, 1, 59.99,  'completed', datetime('now', '-5 days')
    UNION ALL SELECT 5, 6, 4, 19.99,  'pending',   datetime('now', '-1 day')
    UNION ALL SELECT 2, 1, 1, 1899.99,'shipped',   datetime('now', '-2 days')
    UNION ALL SELECT 3, 6, 2, 19.99,  'completed', datetime('now', '-15 days')
) WHERE NOT EXISTS (SELECT 1 FROM orders);
