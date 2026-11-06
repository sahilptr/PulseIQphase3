 
from pathlib import Path
import duckdb

BASE_DIR = Path(r"D:\PulseIQ")
DB_PATH = BASE_DIR / "pulseiq.duckdb"

con = duckdb.connect(str(DB_PATH))

def get_columns(table_name):
    result = con.execute(
        f"DESCRIBE {table_name}"
    ).fetchdf()
    return result["column_name"].tolist()

# Check actual table columns
attendance_cols = get_columns("fact_attendance_monthly")
leave_cols = get_columns("fact_leave")

required_attendance = [
    "period_end_date",
    "department_id",
    "scheduled_days",
    "present_days",
    "late_arrivals"
]

for col in required_attendance:
    if col not in attendance_cols:
        raise ValueError(
            f"Missing attendance column: {col}"
        )

required_leave = [
    "start_date",
    "leave_type_code",
    "days"
]

for col in required_leave:
    if col not in leave_cols:
        raise ValueError(
            f"Missing leave column: {col}"
        )

# Overtime is optional in the cleaned attendance table.
has_overtime = "overtime_hours" in attendance_cols

overtime_expression = (
    "SUM(COALESCE(overtime_hours, 0))"
    if has_overtime
    else "CAST(0 AS DOUBLE)"
)

# 1. Monthly attendance and late arrival metrics
con.execute("""
CREATE OR REPLACE VIEW metric_task6_attendance AS
SELECT
    CAST(date_trunc('month', period_end_date) AS DATE)
        AS month_start,
    department_id,

    COUNT(DISTINCT employee_id) AS employee_count,

    SUM(scheduled_days) AS scheduled_days,
    SUM(present_days) AS present_days,

    SUM(late_arrivals) AS late_arrivals,

    CASE
        WHEN SUM(scheduled_days) > 0
        THEN ROUND(
            100.0 * SUM(present_days)
            / SUM(scheduled_days), 2
        )
        ELSE NULL
    END AS attendance_rate,

    CASE
        WHEN SUM(present_days) > 0
        THEN ROUND(
            100.0 * SUM(late_arrivals)
            / SUM(present_days), 2
        )
        ELSE NULL
    END AS late_arrival_rate

FROM fact_attendance_monthly

GROUP BY
    CAST(date_trunc('month', period_end_date) AS DATE),
    department_id
""")

# 2. Monthly overtime metrics
con.execute(f"""
CREATE OR REPLACE VIEW metric_task6_overtime AS
SELECT
    CAST(date_trunc('month', period_end_date) AS DATE)
        AS month_start,
    department_id,
    SUM(COALESCE(scheduled_days, 0)) AS scheduled_days,
    {overtime_expression} AS overtime_hours
FROM fact_attendance_monthly
GROUP BY
    CAST(date_trunc('month', period_end_date) AS DATE),
    department_id
""")


# 3. Monthly leave by type and department
leave_has_employee_key = "employee_key" in leave_cols

if leave_has_employee_key:
    employee_cols = get_columns("dim_employee")

    if "employee_key" in employee_cols and "department_id" in employee_cols:
        con.execute("""
        CREATE OR REPLACE VIEW metric_task6_leave AS
        SELECT
            CAST(date_trunc('month', l.start_date) AS DATE)
                AS month_start,
            l.leave_type_code,
            l.status,
            e.department_id,
            SUM(COALESCE(l.days, 0)) AS leave_days,
            COUNT(*) AS leave_requests
        FROM fact_leave l
        LEFT JOIN dim_employee e
            ON l.employee_key = e.employee_key
        GROUP BY
            CAST(date_trunc('month', l.start_date) AS DATE),
            l.leave_type_code,
            l.status,
            e.department_id
        """)
    else:
        raise ValueError(
            "dim_employee needs employee_key and department_id"
        )
else:
    raise ValueError(
        "fact_leave does not contain employee_key. "
        "Check its schema before joining departments."
    )

# 4. Overall monthly attendance
con.execute("""
CREATE OR REPLACE VIEW metric_task6_monthly AS
SELECT
    month_start,
    SUM(scheduled_days) AS scheduled_days,
    SUM(present_days) AS present_days,
    SUM(late_arrivals) AS late_arrivals,
    ROUND(
        100.0 * SUM(present_days)
        / NULLIF(SUM(scheduled_days), 0),
        2
    ) AS attendance_rate
FROM metric_task6_attendance
GROUP BY month_start
""")

# Verify views
print("\nTASK 6 METRIC VIEWS CREATED SUCCESSFULLY")

for view in [
    "metric_task6_attendance",
    "metric_task6_overtime",
    "metric_task6_leave",
    "metric_task6_monthly"
]:
    print(f"\n--- {view} ---")
    print(
        con.execute(
            f"SELECT * FROM {view} LIMIT 5"
        ).fetchdf().to_string(index=False)
    )

print("\nOvertime column available:", has_overtime)

con.close()

print("\nTask 6 metric building completed.")
