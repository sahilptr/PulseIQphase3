
from pathlib import Path
import duckdb

db = Path(r"D:\PulseIQ\pulseiq.duckdb")
con = duckdb.connect(str(db), read_only=True)

print("\n===== TASK STATUS VALUES =====")
print(con.execute("""
    SELECT status, COUNT(*) AS rows
    FROM fact_task
    GROUP BY status
    ORDER BY rows DESC
""").df().to_string(index=False))

print("\n===== TASK DATE AND DEPARTMENT SAMPLE =====")
print(con.execute("""
    SELECT
        f.task_id,
        f.assignee_employee_id,
        f.status,
        f.completed_date,
        f.due_date,
        e.department_id
    FROM fact_task f
    LEFT JOIN dim_employee e
        ON f.assignee_employee_id = e.employee_id
    LIMIT 15
""").df().to_string(index=False))

print("\n===== ATTENDANCE OVERTIME TOTALS =====")
print(con.execute("""
    SELECT
        department_id,
        SUM(overtime_hours) AS overtime_hours,
        SUM(scheduled_days) AS scheduled_days,
        COUNT(*) AS rows
    FROM fact_attendance_monthly
    GROUP BY department_id
    ORDER BY department_id
""").df().to_string(index=False))

print("\n===== MONTHLY OVERTIME SAMPLE =====")
print(con.execute("""
    SELECT
        DATE_TRUNC('month', period_end_date)::DATE AS period,
        department_id,
        SUM(overtime_hours) AS overtime_hours,
        SUM(scheduled_days) AS scheduled_days
    FROM fact_attendance_monthly
    GROUP BY 1, 2
    ORDER BY 1, 2
    LIMIT 20
""").df().to_string(index=False))

print("\n===== ATTRITION PRIVACY STATUS =====")
print(con.execute("""
    SELECT privacy_status, COUNT(*) AS rows
    FROM metric_m04_monthly_attrition
    GROUP BY privacy_status
""").df().to_string(index=False))

print("\n===== EMPLOYEE DIMENSION SCHEMA =====")
print(con.execute("""
    DESCRIBE dim_employee
""").df().to_string(index=False))

con.close()
