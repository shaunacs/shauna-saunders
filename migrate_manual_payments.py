"""Migration script to add payment_method_type column to projects table.

Adds support for manual payment methods (Venmo, CashApp, Zelle) alongside Stripe.
Safe to run multiple times - checks if column exists first.

Usage: python migrate_manual_payments.py
"""

import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'customers.db')


def migrate():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}. No migration needed.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check if column already exists
    cursor.execute("PRAGMA table_info(projects)")
    columns = [column[1] for column in cursor.fetchall()]

    if 'payment_method_type' in columns:
        print("Column 'payment_method_type' already exists. No migration needed.")
        conn.close()
        return

    print("Adding 'payment_method_type' column to projects table...")
    cursor.execute("ALTER TABLE projects ADD COLUMN payment_method_type TEXT DEFAULT 'stripe'")

    # Set existing subscription projects with stripe_subscription_id to 'stripe'
    cursor.execute("""
        UPDATE projects
        SET payment_method_type = 'stripe'
        WHERE is_subscription = 1 AND stripe_subscription_id IS NOT NULL
    """)
    stripe_count = cursor.rowcount

    # Set all other subscription projects to 'stripe' as default
    cursor.execute("""
        UPDATE projects
        SET payment_method_type = 'stripe'
        WHERE is_subscription = 1 AND payment_method_type IS NULL
    """)
    default_count = cursor.rowcount

    conn.commit()
    conn.close()

    print(f"Migration complete!")
    print(f"  - {stripe_count} existing Stripe subscription projects updated")
    print(f"  - {default_count} other subscription projects set to 'stripe' default")


if __name__ == '__main__':
    migrate()
