
from pathlib import Path
import duckdb

BASE_DIR = Path(r"D:\PulseIQ")
DB_PATH = BASE_DIR / "pulseiq.duckdb"
EVIDENCE_DIR = BASE_DIR / "evidence"

EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

con = duckdb.connect(str(DB_PATH))

# Combine the three governed Task 4 payroll metrics.
# Only department-month groups passing all privacy checks are visible.
con.execute("""
CREATE OR REPLACE VIEW metric_task9_payroll_dashboard AS
SELECT
    g.period,
    g.department_id,
    d.department_name,

    g.metric_value AS gross_pay,
    n.metric_value AS net_pay,
    e.metric_value AS employer_cost,

    LEAST(
        g.group_size,
        n.group_size,
        e.group_size
    ) AS employee_count,

    CASE
        WHEN g.privacy_status = 'OK'
         AND n.privacy_status = 'OK'
         AND e.privacy_status = 'OK'
         AND LEAST(g.group_size, n.group_size, e.group_size) >= 10
        THEN 'OK'
        ELSE 'SUPPRESSED'
    END AS privacy_status,

    CASE
        WHEN LEAST(g.group_size, n.group_size, e.group_size) >= 10
        THEN e.metric_value /
             NULLIF(LEAST(g.group_size, n.group_size, e.group_size), 0)
        ELSE NULL
    END AS employer_cost_per_employee,

    CASE
        WHEN LEAST(g.group_size, n.group_size, e.group_size) >= 10
        THEN g.metric_value /
             NULLIF(LEAST(g.group_size, n.group_size, e.group_size), 0)
        ELSE NULL
    END AS gross_pay_per_employee

FROM metric_m07_gross_pay g

JOIN metric_m08_net_pay n
    ON g.period = n.period
   AND g.department_id = n.department_id

JOIN metric_m09_payroll_cost e
    ON g.period = e.period
   AND g.department_id = e.department_id

LEFT JOIN dim_department d
    ON g.department_id = d.department_id
""")

# Export only privacy-approved department-month totals.
df = con.execute("""
SELECT *
FROM metric_task9_payroll_dashboard
WHERE privacy_status = 'OK'
ORDER BY period, department_name
""").fetchdf()

df.to_csv(
    EVIDENCE_DIR / "task9_payroll_dashboard_data.csv",
    index=False
)

print("\nPAYROLL DASHBOARD METRIC VIEW CREATED")
print("Visible department-month rows:", len(df))
print(df.head(10).to_string(index=False))

print("\nTOTALS FROM GOVERNED METRIC VIEWS")
print(con.execute("""
SELECT
    SUM(gross_pay) AS gross_pay,
    SUM(net_pay) AS net_pay,
    SUM(employer_cost) AS employer_cost,
    SUM(employee_count) AS employee_months
FROM metric_task9_payroll_dashboard
WHERE privacy_status = 'OK'
""").fetchdf().to_string(index=False))

con.close()
