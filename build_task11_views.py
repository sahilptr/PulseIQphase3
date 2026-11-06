
from pathlib import Path
import duckdb

DB_PATH = Path(__file__).resolve().parent / "pulseiq.duckdb"
con = duckdb.connect(str(DB_PATH))

# Revenue, expenses and profit by month.
# Only detail accounts are included (is_group = 'N').
con.execute("""
CREATE OR REPLACE VIEW v_task11_pnl_monthly AS
SELECT
    l.posting_period AS month,
    SUM(
        CASE WHEN a.account_type = 'INCOME'
        THEN -l.signed_amount_debit_positive ELSE 0 END
    ) AS revenue,
    SUM(
        CASE WHEN a.account_type = 'EXPENSE'
        THEN l.signed_amount_debit_positive ELSE 0 END
    ) AS expenses,
    SUM(
        CASE WHEN a.account_type = 'INCOME'
        THEN -l.signed_amount_debit_positive
        WHEN a.account_type = 'EXPENSE'
        THEN -l.signed_amount_debit_positive
        ELSE 0 END
    ) AS net_profit
FROM fact_ledger l
JOIN dim_account a
    ON CAST(l.account_code AS VARCHAR) = CAST(a.account_code AS VARCHAR)
WHERE
    a.statement = 'Profit & Loss'
    AND a.is_group = 'N'
GROUP BY l.posting_period
ORDER BY l.posting_period
""")

# Expenses by category (excluding GST).
con.execute("""
CREATE OR REPLACE VIEW v_task11_expense_category AS
SELECT
    e.expense_date,
    CAST(e.expense_date AS DATE) AS expense_month_date,
    a.account_name AS category,
    SUM(e.amount_excl_gst) AS expense_amount
FROM fact_expense e
LEFT JOIN dim_account a
    ON CAST(e.category_account AS VARCHAR) =
       CAST(a.account_code AS VARCHAR)
WHERE COALESCE(a.is_group, 'N') = 'N'
GROUP BY e.expense_date, a.account_name
""")

# Top vendors.
con.execute("""
CREATE OR REPLACE VIEW v_task11_vendor_spend AS
SELECT
    v.vendor_id,
    v.vendor_name,
    SUM(e.amount_excl_gst) AS total_spend,
    COUNT(e.expense_id) AS bill_count
FROM fact_expense e
LEFT JOIN dim_vendor v
    ON e.vendor_id = v.vendor_id
GROUP BY v.vendor_id, v.vendor_name
""")

print("Task 11 views created successfully.")

print(con.execute("""
SELECT * FROM v_task11_pnl_monthly
ORDER BY month
LIMIT 5
""").df())

con.close()
