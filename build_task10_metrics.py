
from pathlib import Path
import duckdb

BASE_DIR = Path(r"D:\PulseIQ")
DB_PATH = BASE_DIR / "pulseiq.duckdb"
EVIDENCE_DIR = BASE_DIR / "evidence"

EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

con = duckdb.connect(str(DB_PATH))

# 1. Payroll budget versus actual
con.execute("""
CREATE OR REPLACE VIEW metric_task10_payroll_budget AS
SELECT
    CAST(b.month AS DATE) AS period,
    b.department_id,
    d.department_name,

    b.budget_payroll_cost AS budget_cost,
    p.metric_value AS actual_cost,
    p.group_size,
    p.privacy_status,

    p.metric_value - b.budget_payroll_cost AS variance,

    CASE
        WHEN b.budget_payroll_cost <> 0
        THEN
            (p.metric_value - b.budget_payroll_cost)
            / b.budget_payroll_cost * 100
        ELSE NULL
    END AS variance_pct,

    CASE
        WHEN p.privacy_status <> 'OK' OR p.group_size < 10
            THEN 'SUPPRESSED'
        WHEN p.metric_value > b.budget_payroll_cost
            THEN 'OVER BUDGET'
        WHEN p.metric_value < b.budget_payroll_cost
            THEN 'UNDER BUDGET'
        ELSE 'ON BUDGET'
    END AS budget_status

FROM raw_budget_payroll_dept_month b

JOIN metric_m09_payroll_cost p
    ON CAST(b.month AS DATE) = CAST(p.period AS DATE)
   AND b.department_id = p.department_id

LEFT JOIN dim_department d
    ON b.department_id = d.department_id
""")

# 2. Department ranking by total overspend
con.execute("""
CREATE OR REPLACE VIEW metric_task10_department_ranking AS
SELECT
    department_id,
    department_name,
    SUM(budget_cost) AS total_budget,
    SUM(actual_cost) AS total_actual,
    SUM(variance) AS total_variance,
    CASE
        WHEN SUM(budget_cost) <> 0
        THEN SUM(variance) / SUM(budget_cost) * 100
        ELSE NULL
    END AS variance_pct,
    RANK() OVER (ORDER BY SUM(variance) DESC) AS overspend_rank
FROM metric_task10_payroll_budget
WHERE privacy_status = 'OK'
  AND group_size >= 10
GROUP BY department_id, department_name
ORDER BY overspend_rank
""")

# 3. Export payroll budget evidence
payroll = con.execute("""
SELECT *
FROM metric_task10_payroll_budget
ORDER BY period, department_name
""").fetchdf()

payroll.to_csv(
    EVIDENCE_DIR / "task10_payroll_budget.csv",
    index=False
)

ranking = con.execute("""
SELECT *
FROM metric_task10_department_ranking
ORDER BY overspend_rank
""").fetchdf()

ranking.to_csv(
    EVIDENCE_DIR / "task10_department_ranking.csv",
    index=False
)


# 4. Task completion actual by department and month
con.execute("""
CREATE OR REPLACE VIEW metric_task10_completion AS
SELECT
    DATE_TRUNC('month', due_date)::DATE AS period,
    e.department_id,
    COUNT(*) FILTER (
        WHERE LOWER(TRIM(status)) = 'done'
    ) * 100.0 / NULLIF(COUNT(*), 0) AS actual_value,
    COUNT(DISTINCT assignee_employee_id) AS group_size
FROM fact_task f
JOIN dim_employee e
    ON f.assignee_employee_id = e.employee_id
WHERE due_date IS NOT NULL
GROUP BY 1, 2
""")



# 5. Combine actuals with KPI targets
con.execute("""
CREATE OR REPLACE VIEW metric_task10_kpi_status AS
SELECT
    t.month::DATE AS period,
    t.department_id,
    d.department_name,

    CASE WHEN a.group_size >= 10 THEN a.actual_value END
        AS attendance_actual,
    t.attendance_rate_target * 100 AS attendance_target,

    CASE WHEN o.group_size >= 10 THEN o.actual_value END
        AS overtime_actual,
    t.overtime_share_target_pct AS overtime_target,

    CASE
        WHEN r.privacy_status = 'OK' AND r.group_size >= 10
        THEN r.actual_value
    END AS attrition_actual,
    t.attrition_monthly_target_pct AS attrition_target,

    CASE WHEN c.group_size >= 10 THEN c.actual_value END
        AS completion_actual,
    t.task_completion_target_pct AS completion_target,

    CASE
        WHEN a.group_size < 10 OR a.actual_value IS NULL THEN 'NO DATA'
        WHEN a.actual_value >= t.attendance_rate_target * 100 THEN 'GREEN'
        WHEN a.actual_value >= t.attendance_rate_target * 100 - 5 THEN 'AMBER'
        ELSE 'RED'
    END AS attendance_status,

    CASE
        WHEN o.group_size < 10 OR o.actual_value IS NULL THEN 'NO DATA'
        WHEN o.actual_value <= t.overtime_share_target_pct THEN 'GREEN'
        WHEN o.actual_value <= t.overtime_share_target_pct + 0.5 THEN 'AMBER'
        ELSE 'RED'
    END AS overtime_status,

    CASE
        WHEN r.privacy_status <> 'OK'
          OR r.group_size < 10
          OR r.actual_value IS NULL THEN 'NO DATA'
        WHEN r.actual_value <= t.attrition_monthly_target_pct THEN 'GREEN'
        WHEN r.actual_value <= t.attrition_monthly_target_pct + 0.5 THEN 'AMBER'
        ELSE 'RED'
    END AS attrition_status,

    CASE
        WHEN c.group_size < 10 OR c.actual_value IS NULL THEN 'NO DATA'
        WHEN t.task_completion_target_pct IS NULL THEN 'NO TARGET'
        WHEN c.actual_value >= t.task_completion_target_pct THEN 'GREEN'
        WHEN c.actual_value >= t.task_completion_target_pct - 5 THEN 'AMBER'
        ELSE 'RED'
    END AS completion_status

FROM raw_kpi_targets t
LEFT JOIN dim_department d
    ON t.department_id = d.department_id
LEFT JOIN metric_task10_attendance a
    ON t.department_id = a.department_id
    AND t.month::DATE = a.period
LEFT JOIN metric_task10_overtime o
    ON t.department_id = o.department_id
    AND t.month::DATE = o.period
LEFT JOIN metric_task10_attrition r
    ON t.department_id = r.department_id
    AND t.month::DATE = r.period
LEFT JOIN metric_task10_completion c
    ON t.department_id = c.department_id
    AND t.month::DATE = c.period
""")


# 6. Inspect source schemas for KPI metric creation in the next step
for table in [
    "fact_attendance_monthly",
    "fact_task",
    "fact_headcount_monthly"
]:
    print(f"\n========== {table} SCHEMA ==========")
    print(
        con.execute(f"DESCRIBE {table}")
        .fetchdf()
        .to_string(index=False)
    )

print("\n========== KPI TARGET SAMPLE ==========")
print(
    con.execute("""
        SELECT *
        FROM raw_kpi_targets
        ORDER BY month, department_id
        LIMIT 10
    """).fetchdf().to_string(index=False)
)

con.close()

print("\nTask 10 Step 1 completed.")
print("Evidence saved in:", EVIDENCE_DIR)
