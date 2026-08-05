-- ============================================================
-- AI SQL Agent - sample/dev schema for the compose Postgres.
-- Creates a small e-commerce dataset so the agent has something
-- to query on first boot.
-- ============================================================

CREATE TABLE IF NOT EXISTS products (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,
    price       NUMERIC(10, 2) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS customers (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    country     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orders (
    id           SERIAL PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    product_id   INTEGER NOT NULL REFERENCES products(id),
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    unit_price   NUMERIC(10, 2) NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_product  ON orders(product_id);

-- Seed data (idempotent: only insert when empty)
INSERT INTO products (name, category, price)
SELECT * FROM (VALUES
    ('Laptop Pro 16', 'electronics', 1899.99),
    ('Wireless Mouse', 'electronics', 49.99),
    ('Mechanical Keyboard', 'electronics', 129.99),
    ('USB-C Hub', 'electronics', 79.99),
    ('Desk Lamp', 'home', 59.99),
    ('Coffee Mug 500ml', 'home', 19.99)
) AS seed(name, category, price)
WHERE NOT EXISTS (SELECT 1 FROM products);

INSERT INTO customers (email, name, country)
SELECT * FROM (VALUES
    ('alice@example.com', 'Alice Smith',   'US'),
    ('bob@example.com',   'Bob Jones',     'US'),
    ('carol@example.com', 'Carol Nguyen',  'CA'),
    ('dave@example.com',  'Dave Patel',    'UK'),
    ('erin@example.com',  'Erin Garcia',   'MX')
) AS seed(email, name, country)
WHERE NOT EXISTS (SELECT 1 FROM customers);

INSERT INTO orders (customer_id, product_id, quantity, unit_price, status, created_at)
SELECT c.id, p.id, seed.qty, p.price, seed.status, seed.created_at
FROM (VALUES
    (1, 1, 2, 1899.99, 'completed', now() - interval '40 days'),
    (1, 2, 1, 49.99,   'completed', now() - interval '30 days'),
    (2, 3, 1, 129.99,  'completed', now() - interval '25 days'),
    (3, 4, 2, 79.99,   'shipped',   now() - interval '10 days'),
    (4, 5, 1, 59.99,   'completed', now() - interval '5 days'),
    (5, 6, 4, 19.99,   'pending',   now() - interval '1 day'),
    (2, 1, 1, 1899.99, 'shipped',   now() - interval '2 days'),
    (3, 6, 2, 19.99,   'completed', now() - interval '15 days')
) AS seed(customer_id, product_id, qty, unit_price, status, created_at)
JOIN customers c ON c.id = seed.customer_id
JOIN products p  ON p.id  = seed.product_id
WHERE NOT EXISTS (SELECT 1 FROM orders);
