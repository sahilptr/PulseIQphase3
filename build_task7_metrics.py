
from pathlib import Path
import duckdb

DB_PATH = Path(r"D:\PulseIQ\pulseiq.duckdb")
con = duckdb.connect(str(DB_PATH))

def columns(table):
    return con.execute(f"DESCRIBE {table}").fetchdf()[
        "column_name"
    ].tolist()

# --------------------------------------------------
# 1. CHECK EXISTING GOVERNED ATTRITION METRICS
# --------------------------------------------------

required_views = [
    "metric_m03_exits",
    "metric_m04_monthly_attrition",
    "metric_m05_rolling_12m_attrition",
    "metric_m06_voluntary_attrition"
]

existing_views = con.execute("""
SELECT table_name
FROM information_schema.views
""").fetchdf()["table_name"].tolist()

for view in required_views:
    if view not in existing_views:
        raise ValueError(
            f"Missing Task 4 metric view: {view}"
        )

print("\nEXISTING ATTRITION METRIC VIEWS")
for view in required_views:
    print(f"\n{view}")
    print(con.execute(f"DESCRIBE {view}").fetchdf().to_string(index=False))

# --------------------------------------------------
# 2. MONTHLY ACTUAL EXITS
# --------------------------------------------------

headcount_cols = columns("fact_headcount_monthly")

required = [
    "month_start_date",
    "department_id",
    "headcount_start",
    "exits",
    "voluntary_exits"
]

for col in required:
    if col not in headcount_cols:
        raise ValueError(f"Missing column: {col}")

con.execute("""
CREATE OR REPLACE VIEW metric_task7_actual AS
SELECT
    CAST(month_start_date AS DATE) AS month_start,
    department_id,

    SUM(headcount_start) AS headcount_start,
    SUM(exits) AS exits,
    SUM(voluntary_exits) AS voluntary_exits,

    SUM(exits) - SUM(voluntary_exits) AS other_exits,

    CASE
        WHEN SUM(headcount_start) >= 10
        THEN ROUND(
            100.0 * SUM(exits)
            / NULLIF(SUM(headcount_start), 0), 2
        )
        ELSE NULL
    END AS attrition_rate,

    CASE
        WHEN SUM(headcount_start) >= 10
        THEN ROUND(
            100.0 * SUM(voluntary_exits)
            / NULLIF(SUM(headcount_start), 0), 2
        )
        ELSE NULL
    END AS voluntary_attrition_rate,

    CASE
        WHEN SUM(headcount_start) >= 10
        THEN 'VISIBLE'
        ELSE 'SUPPRESSED'
    END AS privacy_status

FROM fact_headcount_monthly

GROUP BY
    CAST(month_start_date AS DATE),
    department_id
""")

# --------------------------------------------------
# 3. PREDICTED RISK - AGGREGATED ONLY
# --------------------------------------------------

risk_cols = columns("fact_attrition_risk")

risk_required = [
    "employee_key",
    "department_id",
    "as_of_date",
    "risk_score_12m",
    "risk_band"
]

for col in risk_required:
    if col not in risk_cols:
        raise ValueError(
            f"Missing prediction column: {col}"
        )

con.execute("""
CREATE OR REPLACE VIEW metric_task7_predicted AS
SELECT
    CAST(date_trunc('month', as_of_date) AS DATE)
        AS month_start,

    department_id,
    risk_band,

    COUNT(DISTINCT employee_key) AS group_size,

    ROUND(
        AVG(risk_score_12m) * 100, 2
    ) AS average_predicted_risk_pct,

    CASE
        WHEN AVG(risk_score_12m) >= 0.70
        THEN 'Higher average predicted risk'
        WHEN AVG(risk_score_12m) >= 0.40
        THEN 'Moderate average predicted risk'
        ELSE 'Lower average predicted risk'
    END AS group_risk_description

FROM fact_attrition_risk

GROUP BY
    CAST(date_trunc('month', as_of_date) AS DATE),
    department_id,
    risk_band

HAVING COUNT(DISTINCT employee_key) >= 10
""")

# --------------------------------------------------
# 4. TENURE AT EXIT
# --------------------------------------------------

employee_cols = columns("dim_employee")

start_candidates = [
    "hire_date",
    "employment_start_date",
    "effective_start_date",
    "start_date"
]

end_candidates = [
    "exit_date",
    "termination_date",
    "employment_end_date"
]

start_col = next(
    (c for c in start_candidates if c in employee_cols),
    None
)

end_col = next(
    (c for c in end_candidates if c in employee_cols),
    None
)

if (
    start_col
    and end_col
    and "employee_key" in employee_cols
    and "department_id" in employee_cols
):
    con.execute(f"""
    CREATE OR REPLACE VIEW metric_task7_tenure AS

    WITH exited AS (
        SELECT
            employee_key,
            department_id,
            CAST({start_col} AS DATE) AS hire_date,
            CAST({end_col} AS DATE) AS exit_date,

            ROW_NUMBER() OVER (
                PARTITION BY employee_key
                ORDER BY CAST({end_col} AS DATE) DESC
            ) AS rn

        FROM dim_employee
        WHERE {end_col} IS NOT NULL
          AND {start_col} IS NOT NULL
    ),

    tenure AS (
        SELECT
            department_id,

            date_diff(
                'day', hire_date, exit_date
            ) / 365.25 AS tenure_years

        FROM exited
        WHERE rn = 1
          AND exit_date >= hire_date
    )

    SELECT
        department_id,

        CASE
            WHEN tenure_years < 1 THEN 'Less than 1 year'
            WHEN tenure_years < 3 THEN '1-3 years'
            WHEN tenure_years < 5 THEN '3-5 years'
            ELSE '5+ years'
        END AS tenure_band,

        COUNT(*) AS exits,

        ROUND(AVG(tenure_years), 2)
            AS average_tenure_years

    FROM tenure
    GROUP BY
        department_id,
        CASE
            WHEN tenure_years < 1 THEN 'Less than 1 year'
            WHEN tenure_years < 3 THEN '1-3 years'
            WHEN tenure_years < 5 THEN '3-5 years'
            ELSE '5+ years'
        END

    HAVING COUNT(*) >= 5
    """)
    print("\nTenure view created.")
else:
    print(
        "\nWARNING: Could not identify hire and exit dates "
        "in dim_employee. Tenure view was not created."
    )

# --------------------------------------------------
# 5. VERIFY OUTPUTS
# --------------------------------------------------

for view in [
    "metric_task7_actual",
    "metric_task7_predicted"
]:
    print(f"\n--- {view} ---")
    print(
        con.execute(
            f"SELECT * FROM {view} LIMIT 10"
        ).fetchdf().to_string(index=False)
    )

if (
    start_col
    and end_col
    and "employee_key" in employee_cols
):
    print("\n--- metric_task7_tenure ---")
    print(
        con.execute("""
        SELECT * FROM metric_task7_tenure
        LIMIT 10
        """).fetchdf().to_string(index=False)
    )

print("\nTask 7 metric views created.")

con.close()
