
from pathlib import Path
import duckdb

BASE_DIR = Path(r"D:\PulseIQ")
DB_PATH = BASE_DIR / "pulseiq.duckdb"

con = duckdb.connect(str(DB_PATH))

# 1. Attendance actual by department and month
con.execute("""
CREATE OR REPLACE VIEW metric_task10_attendance AS
SELECT
    DATE_TRUNC('month', period_end_date)::DATE AS period,
    department_id,
    AVG(attendance_rate) * 100 AS actual_value,
    COUNT(DISTINCT employee_id) AS group_size
FROM fact_attendance_monthly
GROUP BY 1, 2
""")

# 2. Overtime share actual by department and month
con.execute("""
CREATE OR REPLACE VIEW metric_task10_overtime AS
SELECT
    DATE_TRUNC('month', period_end_date)::DATE AS period,
    department_id,
    CASE
        WHEN SUM(scheduled_days) > 0
        THEN SUM(overtime_hours) /
             (SUM(scheduled_days) * 8.0) * 100
        ELSE NULL
    END AS actual_value,
    COUNT(DISTINCT employee_id) AS group_size
FROM fact_attendance_monthly
GROUP BY 1, 2
""")

# 3. Monthly attrition actual
con.execute("""
CREATE OR REPLACE VIEW metric_task10_attrition AS
SELECT
    CAST(period AS DATE) AS period,
    department_id,
    metric_value AS actual_value,
    group_size,
    privacy_status
FROM metric_m04_monthly_attrition
""")

# 4. Task completion actual by department and month
con.execute("""
CREATE OR REPLACE VIEW metric_task10_completion AS
SELECT
    DATE_TRUNC('month', COALESCE(completed_date, due_date))::DATE AS period,
    d.department_id,
    COUNT(*) FILTER (
        WHERE LOWER(status) = 'completed'
    ) * 100.0 / NULLIF(COUNT(*), 0) AS actual_value,
    COUNT(*) AS group_size
FROM fact_task f
JOIN dim_employee e
    ON f.assignee_employee_id = e.employee_id
JOIN dim_department d
    ON e.department_id = d.department_id
WHERE COALESCE(f.completed_date, f.due_date) IS NOT NULL
GROUP BY 1, 2
""")

# 5. Combine actuals with KPI targets
con.execute("""
CREATE OR REPLACE VIEW metric_task10_kpi_status AS
SELECT
    t.month::DATE AS period,
    t.department_id,
    d.department_name,

    a.actual_value AS attendance_actual,
    t.attendance_rate_target * 100 AS attendance_target,

    o.actual_value AS overtime_actual,
    t.overtime_share_target_pct AS overtime_target,

    r.actual_value AS attrition_actual,
    t.attrition_monthly_target_pct AS attrition_target,

    c.actual_value AS completion_actual,
    t.task_completion_target_pct AS completion_target,

    CASE
        WHEN a.actual_value IS NULL THEN 'NO DATA'
        WHEN a.actual_value >= t.attendance_rate_target * 100 THEN 'GREEN'
        WHEN a.actual_value >= t.attendance_rate_target * 100 - 5 THEN 'AMBER'
        ELSE 'RED'
    END AS attendance_status,

    CASE
        WHEN o.actual_value IS NULL THEN 'NO DATA'
        WHEN o.actual_value <= t.overtime_share_target_pct THEN 'GREEN'
        WHEN o.actual_value <= t.overtime_share_target_pct + 0.5 THEN 'AMBER'
        ELSE 'RED'
    END AS overtime_status,

    CASE
        WHEN r.actual_value IS NULL THEN 'NO DATA'
        WHEN r.actual_value <= t.attrition_monthly_target_pct THEN 'GREEN'
        WHEN r.actual_value <= t.attrition_monthly_target_pct + 0.5 THEN 'AMBER'
        ELSE 'RED'
    END AS attrition_status,

    CASE
        WHEN c.actual_value IS NULL THEN 'NO DATA'
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

# Export KPI status evidence
out = con.execute("""
SELECT *
FROM metric_task10_kpi_status
ORDER BY period, department_id
""").df()

out.to_csv(BASE_DIR / "evidence" / "task10_kpi_status.csv", index=False)

print("========== KPI STATUS CREATED ==========")
print("Rows:", len(out))
print(out.head(15).to_string(index=False))

print("\n========== KPI STATUS COUNTS ==========")
for col in [
    "attendance_status",
    "overtime_status",
    "attrition_status",
    "completion_status"
]:
    print(f"\n{col}")
    print(out[col].value_counts(dropna=False).to_string())

con.close()
print("\nSaved: evidence/task10_kpi_status.csv")
