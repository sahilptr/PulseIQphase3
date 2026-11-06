from pathlib import Path
import csv
import duckdb

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "pulseiq.duckdb"
EVIDENCE_DIR = BASE_DIR / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

if not DB_PATH.exists():
    raise FileNotFoundError(f"Database not found: {DB_PATH}")

# Each view returns a consistent metric_value column. People-related metrics
# suppress small groups by returning NULL when the minimum group size is not met.
VIEWS = {
"metric_m01_headcount": """
SELECT month_start_date AS period, department_id,
       CASE WHEN headcount_end < 5 THEN NULL ELSE headcount_end::DOUBLE END AS metric_value,
       headcount_end AS group_size,
       CASE WHEN headcount_end < 5 THEN 'SUPPRESSED' ELSE 'OK' END AS privacy_status
FROM fact_headcount_monthly
""",
"metric_m02_hires": """
SELECT month_start_date AS period, department_id,
       CASE WHEN headcount_end < 5 THEN NULL ELSE hires::DOUBLE END AS metric_value,
       headcount_end AS group_size,
       CASE WHEN headcount_end < 5 THEN 'SUPPRESSED' ELSE 'OK' END AS privacy_status
FROM fact_headcount_monthly
""",
"metric_m03_exits": """
SELECT month_start_date AS period, department_id,
       CASE WHEN headcount_end < 5 THEN NULL ELSE exits::DOUBLE END AS metric_value,
       headcount_end AS group_size,
       CASE WHEN headcount_end < 5 THEN 'SUPPRESSED' ELSE 'OK' END AS privacy_status
FROM fact_headcount_monthly
""",
"metric_m04_monthly_attrition": """
SELECT month_start_date AS period, department_id, exits::DOUBLE AS numerator,
       headcount_start::DOUBLE AS denominator,
       CASE WHEN headcount_start < 10 OR headcount_start = 0 THEN NULL
            ELSE 100.0 * exits / headcount_start END AS metric_value,
       headcount_start AS group_size,
       CASE WHEN headcount_start < 10 THEN 'SUPPRESSED' ELSE 'OK' END AS privacy_status
FROM fact_headcount_monthly
""",
"metric_m05_rolling_12m_attrition": """
WITH x AS (
 SELECT month_start_date AS period, department_id, exits, headcount_end,
        SUM(exits) OVER w AS exits_12m,
        AVG(headcount_end) OVER w AS avg_headcount_12m,
        COUNT(*) OVER w AS months_in_window,
        MIN(headcount_end) OVER w AS min_headcount_window
 FROM fact_headcount_monthly
 WINDOW w AS (PARTITION BY department_id ORDER BY month_start_date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
)
SELECT period, department_id, exits_12m::DOUBLE AS numerator, avg_headcount_12m::DOUBLE AS denominator,
       CASE WHEN months_in_window < 12 OR min_headcount_window < 10 OR avg_headcount_12m = 0 THEN NULL
            ELSE 100.0 * exits_12m / avg_headcount_12m END AS metric_value,
       min_headcount_window AS group_size,
       CASE WHEN months_in_window < 12 OR min_headcount_window < 10 THEN 'SUPPRESSED_OR_INCOMPLETE' ELSE 'OK' END AS privacy_status
FROM x
""",
"metric_m06_voluntary_attrition": """
WITH x AS (
 SELECT month_start_date AS period, department_id, voluntary_exits, headcount_end,
        SUM(voluntary_exits) OVER w AS voluntary_exits_12m,
        AVG(headcount_end) OVER w AS avg_headcount_12m,
        COUNT(*) OVER w AS months_in_window,
        MIN(headcount_end) OVER w AS min_headcount_window
 FROM fact_headcount_monthly
 WINDOW w AS (PARTITION BY department_id ORDER BY month_start_date ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
)
SELECT period, department_id, voluntary_exits_12m::DOUBLE AS numerator, avg_headcount_12m::DOUBLE AS denominator,
       CASE WHEN months_in_window < 12 OR min_headcount_window < 10 OR avg_headcount_12m = 0 THEN NULL
            ELSE 100.0 * voluntary_exits_12m / avg_headcount_12m END AS metric_value,
       min_headcount_window AS group_size,
       CASE WHEN months_in_window < 12 OR min_headcount_window < 10 THEN 'SUPPRESSED_OR_INCOMPLETE' ELSE 'OK' END AS privacy_status
FROM x
""",
"metric_m07_gross_pay": """
SELECT CAST(date_trunc('month', period_end_date) AS DATE) AS period, department_id,
       CASE WHEN COUNT(DISTINCT employee_id) < 5 THEN NULL ELSE SUM(gross_pay) END AS metric_value,
       COUNT(DISTINCT employee_id) AS group_size,
       CASE WHEN COUNT(DISTINCT employee_id) < 5 THEN 'SUPPRESSED' ELSE 'OK' END AS privacy_status
FROM fact_payroll GROUP BY 1, 2
""",
"metric_m08_net_pay": """
SELECT CAST(date_trunc('month', period_end_date) AS DATE) AS period, department_id,
       CASE WHEN COUNT(DISTINCT employee_id) < 5 THEN NULL ELSE SUM(net_pay) END AS metric_value,
       COUNT(DISTINCT employee_id) AS group_size,
       CASE WHEN COUNT(DISTINCT employee_id) < 5 THEN 'SUPPRESSED' ELSE 'OK' END AS privacy_status
FROM fact_payroll GROUP BY 1, 2
""",
"metric_m09_payroll_cost": """
SELECT CAST(date_trunc('month', period_end_date) AS DATE) AS period, department_id,
       CASE WHEN COUNT(DISTINCT employee_id) < 5 THEN NULL ELSE SUM(employer_cost) END AS metric_value,
       COUNT(DISTINCT employee_id) AS group_size,
       CASE WHEN COUNT(DISTINCT employee_id) < 5 THEN 'SUPPRESSED' ELSE 'OK' END AS privacy_status
FROM fact_payroll GROUP BY 1, 2

""",
"R02_ledger_debits_credits": """
SELECT CAST(date_trunc('month', entry_date) AS DATE) AS period,
       SUM(debit) AS total_debits, SUM(credit) AS total_credits,
       SUM(debit)-SUM(credit) AS difference,
       CASE WHEN ABS(SUM(debit)-SUM(credit)) <= 1 THEN 'PASS' ELSE 'REVIEW' END AS status
FROM fact_ledger GROUP BY 1
""",
"R03_payroll_totals_vs_reference": """
WITH p AS (
 SELECT strftime(period_end_date, '%Y-%m') AS month, SUM(gross_pay) AS gross_pay,
        SUM(net_pay) AS net_pay, SUM(employer_cost) AS employer_cost
 FROM fact_payroll GROUP BY 1
)
SELECT p.month, p.gross_pay, r.payroll_gross_pay, p.net_pay, r.payroll_net_pay,
       p.employer_cost, r.payroll_employer_cost,
       CASE WHEN ABS(p.gross_pay-r.payroll_gross_pay)<=1 AND ABS(p.net_pay-r.payroll_net_pay)<=1
                  AND ABS(p.employer_cost-r.payroll_employer_cost)<=1 THEN 'PASS' ELSE 'REVIEW' END AS status
FROM p JOIN raw_reconciliation_answer_key r ON p.month = r.month
""",
"R04_revenue_vs_reference": """
WITH l AS (
 SELECT strftime(entry_date, '%Y-%m') AS month,
        -SUM(signed_amount_debit_positive) AS revenue
 FROM fact_ledger WHERE account_code BETWEEN 4001 AND 4004 GROUP BY 1
)
SELECT l.month, l.revenue, r.ledger_revenue,
       l.revenue-r.ledger_revenue AS difference,
       CASE WHEN ABS(l.revenue-r.ledger_revenue)<=1 THEN 'PASS' ELSE 'REVIEW' END AS status
FROM l JOIN raw_reconciliation_answer_key r ON l.month = r.month
""",
"R05_net_profit_vs_reference": """
WITH l AS (
 SELECT strftime(entry_date, '%Y-%m') AS month,
        -SUM(signed_amount_debit_positive) AS net_profit
 FROM fact_ledger WHERE account_code BETWEEN 4000 AND 4999 OR account_code BETWEEN 5000 AND 5999
 GROUP BY 1
)
SELECT l.month, l.net_profit, r.ledger_net_profit,
       l.net_profit-r.ledger_net_profit AS difference,
       CASE WHEN ABS(l.net_profit-r.ledger_net_profit)<=1 THEN 'PASS' ELSE 'REVIEW' END AS status
FROM l JOIN raw_reconciliation_answer_key r ON l.month = r.month
""",
}



# Separate reconciliation views from official metric views.
RECONCILIATIONS = {
    name: VIEWS.pop(name)
    for name in list(VIEWS)
    if name.startswith("R")
}

con = duckdb.connect(str(DB_PATH))
try:
    # Confirm required warehouse tables/columns before changing any views.
    required = {
        "fact_headcount_monthly", "fact_payroll", "fact_attendance_monthly",
        "fact_ledger", "fact_invoice", "fact_task", "fact_anomaly",
        "fact_attrition_risk", "fact_forecast", "raw_reconciliation_answer_key"
    }
    present = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError("Missing required tables: " + ", ".join(missing))

    for view_name, sql in VIEWS.items():
        con.execute(f'DROP VIEW IF EXISTS "{view_name}"')
        con.execute(f'CREATE VIEW "{view_name}" AS {sql}')

    for view_name, sql in RECONCILIATIONS.items():
        con.execute(f'DROP VIEW IF EXISTS "{view_name}"')
        con.execute(f'CREATE VIEW "{view_name}" AS {sql}')

    # View inventory evidence.
    view_names = list(VIEWS) + list(RECONCILIATIONS)
    with open(EVIDENCE_DIR / "metric_view_inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["view_name", "view_type", "row_count", "status"])
        for name in view_names:
            count = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            typ = "metric" if name.startswith("metric_") else "reconciliation"
            w.writerow([name, typ, count, "CREATED"])

    # Export each reconciliation view to its own CSV and a combined summary.
    combined = []
    for name in RECONCILIATIONS:
        rows = con.execute(f'SELECT * FROM "{name}"').fetchall()
        cols = [d[0] for d in con.description]
        with open(EVIDENCE_DIR / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(cols); w.writerows(rows)
        for row in rows:
            combined.append([name, *row])
    with open(EVIDENCE_DIR / "reconciliation_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["check_name", "result_columns..."]); w.writerows(combined)

    # Export privacy suppression counts for each metric view where applicable.
    with open(EVIDENCE_DIR / "privacy_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["view_name", "rows", "suppressed_rows"])
        for name in VIEWS:
            cols = {r[1] for r in con.execute(f"PRAGMA table_info('{name}')").fetchall()}
            if "privacy_status" in cols:
                rows, suppressed = con.execute(
                    f"SELECT COUNT(*), COUNT(*) FILTER (WHERE privacy_status LIKE 'SUPPRESSED%') FROM \"{name}\""
                ).fetchone()
            else:
                rows, suppressed = con.execute(f'SELECT COUNT(*), 0 FROM "{name}"').fetchone()
            w.writerow([name, rows, suppressed])

    print(f"Created {len(VIEWS)} metric views and {len(RECONCILIATIONS)} reconciliation views.")
    print("Evidence written to the evidence folder:")
    print(" - metric_view_inventory.csv")
    print(" - privacy_summary.csv")
    print(" - reconciliation_summary.csv and R01-R05 CSV files")
    print("IMPORTANT: review reconciliation outputs; this script does not change warehouse source data.")
finally:
    con.close()