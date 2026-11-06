
from pathlib import Path
import duckdb
import pandas as pd

BASE_DIR = Path(r"D:\PulseIQ")
DB_PATH = BASE_DIR / "pulseiq.duckdb"
EVIDENCE_DIR = BASE_DIR / "evidence"

EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

con = duckdb.connect(str(DB_PATH))

# --------------------------------------------------
# 1. CHECK REQUIRED COLUMNS
# --------------------------------------------------

def get_columns(table):
    return con.execute(
        f"DESCRIBE {table}"
    ).fetchdf()["column_name"].tolist()


required_task_columns = [
    "task_id",
    "team_id",
    "sprint_id",
    "story_points",
    "status",
    "reopened_count",
    "cycle_time_days",
    "completed_on_time"
]

task_columns = get_columns("fact_task")

for col in required_task_columns:
    if col not in task_columns:
        raise ValueError(f"Missing fact_task column: {col}")

print("Required task columns verified.")

# --------------------------------------------------
# 2. CREATE GOVERNED TEAM PRODUCTIVITY VIEW
# --------------------------------------------------

con.execute("""
CREATE OR REPLACE VIEW metric_task8_productivity AS

WITH task_data AS (
    SELECT
        task_id,
        team_id,
        sprint_id,
        COALESCE(story_points, 0) AS story_points,
        LOWER(TRIM(COALESCE(status, ''))) AS task_status,
        COALESCE(reopened_count, 0) AS reopened_count,
        cycle_time_days,
        UPPER(TRIM(COALESCE(completed_on_time, 'N')))
            AS on_time_flag

    FROM fact_task
),

aggregated AS (
    SELECT
        team_id,
        sprint_id,

        COUNT(*) AS total_tasks,

        COUNT(*) FILTER (
            WHERE task_status IN ('cancelled', 'canceled')
        ) AS cancelled_tasks,

        COUNT(*) FILTER (
            WHERE task_status NOT IN ('cancelled', 'canceled')
        ) AS eligible_tasks,

        COUNT(*) FILTER (
            WHERE task_status = 'done'
        ) AS completed_tasks,

        COUNT(*) FILTER (
            WHERE task_status = 'done'
              AND on_time_flag = 'Y'
        ) AS on_time_tasks,

        COUNT(*) FILTER (
            WHERE task_status = 'blocked'
        ) AS blocked_tasks,

        COUNT(*) FILTER (
            WHERE task_status NOT IN ('cancelled', 'canceled')
              AND reopened_count > 0
        ) AS reopened_tasks,

        SUM(reopened_count) AS total_reopen_events,

        SUM(
            CASE
                WHEN task_status = 'done'
                THEN story_points
                ELSE 0
            END
        ) AS velocity,

        AVG(
            CASE
                WHEN task_status = 'done'
                THEN cycle_time_days
            END
        ) AS average_cycle_time

    FROM task_data
    GROUP BY team_id, sprint_id
)

SELECT
    a.team_id,
    t.team_name,
    t.department_id,
    t.active_members,

    a.sprint_id,
    s.sprint_name,
    s.start_date,
    s.end_date,
    s.working_days,

    a.total_tasks,
    a.eligible_tasks,
    a.cancelled_tasks,
    a.completed_tasks,
    a.on_time_tasks,
    a.blocked_tasks,
    a.reopened_tasks,
    a.total_reopen_events,

    a.velocity,

    ROUND(
        a.average_cycle_time, 2
    ) AS average_cycle_time,

    ROUND(
        100.0 * a.completed_tasks
        / NULLIF(a.eligible_tasks, 0), 2
    ) AS completion_rate,

    ROUND(
        100.0 * a.on_time_tasks
        / NULLIF(a.completed_tasks, 0), 2
    ) AS on_time_rate,

    ROUND(
        a.velocity / NULLIF(s.working_days, 0), 2
    ) AS velocity_per_working_day,

    ROUND(
        a.velocity / NULLIF(t.active_members, 0), 2
    ) AS velocity_per_active_member,

    ROUND(
        100.0 * a.reopened_tasks
        / NULLIF(a.completed_tasks, 0), 2
    ) AS reopened_task_rate,

    CASE
        WHEN a.total_tasks = 0 THEN 'NO DATA'
        ELSE 'AVAILABLE'
    END AS data_status

FROM aggregated a

LEFT JOIN dim_team t
    ON a.team_id = t.team_id

LEFT JOIN dim_sprint s
    ON a.sprint_id = s.sprint_id
""")

# --------------------------------------------------
# 3. CREATE STATUS SUMMARY
# --------------------------------------------------

con.execute("""
CREATE OR REPLACE VIEW metric_task8_status AS
SELECT
    team_id,
    sprint_id,
    TRIM(status) AS task_status,
    COUNT(*) AS task_count
FROM fact_task
GROUP BY team_id, sprint_id, TRIM(status)
""")

# --------------------------------------------------
# 4. CREATE TEAM SUMMARY
# --------------------------------------------------

con.execute("""
CREATE OR REPLACE VIEW metric_task8_team_summary AS
SELECT
    team_id,
    team_name,
    department_id,
    active_members,

    SUM(velocity) AS total_velocity,
    SUM(completed_tasks) AS total_completed,
    SUM(eligible_tasks) AS total_eligible,
    SUM(blocked_tasks) AS total_blocked,
    SUM(reopened_tasks) AS total_reopened,

    ROUND(
        100.0 * SUM(on_time_tasks)
        / NULLIF(SUM(completed_tasks), 0), 2
    ) AS on_time_rate,

    ROUND(
        100.0 * SUM(completed_tasks)
        / NULLIF(SUM(eligible_tasks), 0), 2
    ) AS completion_rate,

    ROUND(
        100.0 * SUM(reopened_tasks)
        / NULLIF(SUM(completed_tasks), 0), 2
    ) AS reopened_task_rate,

    ROUND(
        SUM(velocity) / NULLIF(SUM(working_days), 0), 2
    ) AS velocity_per_working_day

FROM metric_task8_productivity
GROUP BY
    team_id,
    team_name,
    department_id,
    active_members
""")

# --------------------------------------------------
# 5. EXPORT TWO-TEAM MANUAL VERIFICATION DATA
# --------------------------------------------------

team_candidates = con.execute("""
SELECT
    t.team_id,
    t.team_name,
    COUNT(f.task_id) AS task_count
FROM dim_team t
JOIN fact_task f
    ON t.team_id = f.team_id
GROUP BY t.team_id, t.team_name
ORDER BY task_count DESC
LIMIT 2
""").fetchdf()

if len(team_candidates) < 2:
    raise ValueError("At least two teams are required for verification.")

selected_ids = team_candidates["team_id"].tolist()

team_ids_sql = ", ".join(
    "'" + str(x).replace("'", "''") + "'"
    for x in selected_ids
)

# Raw task-level records for manual checking
verification_rows = con.execute(f"""
SELECT
    task_id,
    team_id,
    sprint_id,
    story_points,
    status,
    reopened_count,
    cycle_time_days,
    completed_on_time
FROM fact_task
WHERE CAST(team_id AS VARCHAR) IN ({team_ids_sql})
ORDER BY team_id, sprint_id, task_id
""").fetchdf()

verification_rows.to_csv(
    EVIDENCE_DIR / "task8_two_team_raw_verification.csv",
    index=False
)

verification_summary = con.execute(f"""
SELECT *
FROM metric_task8_productivity
WHERE CAST(team_id AS VARCHAR) IN ({team_ids_sql})
ORDER BY team_id, sprint_id
""").fetchdf()

verification_summary.to_csv(
    EVIDENCE_DIR / "task8_two_team_metric_verification.csv",
    index=False
)

team_candidates.to_csv(
    EVIDENCE_DIR / "task8_selected_teams.csv",
    index=False
)

# --------------------------------------------------
# 6. DISPLAY OUTPUTS
# --------------------------------------------------

print("\nTASK 8 PRODUCTIVITY METRICS")

print(
    con.execute("""
    SELECT *
    FROM metric_task8_productivity
    LIMIT 10
    """).fetchdf().to_string(index=False)
)

print("\nTEAM SUMMARY")

print(
    con.execute("""
    SELECT *
    FROM metric_task8_team_summary
    ORDER BY total_velocity DESC
    """).fetchdf().to_string(index=False)
)

print("\nTWO TEAMS SELECTED FOR MANUAL VERIFICATION")

print(team_candidates.to_string(index=False))

print("\nEVIDENCE FILES CREATED:")
print("task8_two_team_raw_verification.csv")
print("task8_two_team_metric_verification.csv")
print("task8_selected_teams.csv")

con.close()

print("\nTASK 8 METRIC BUILD COMPLETED SUCCESSFULLY.")
