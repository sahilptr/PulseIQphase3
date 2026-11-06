
from pathlib import Path
import duckdb
import csv

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "pulseiq.duckdb"
EVIDENCE_DIR = BASE_DIR / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

if not DB_PATH.exists():
    raise FileNotFoundError(f"Database not found: {DB_PATH}")

METRICS = [
    ("M01", "Headcount", "Active employees at month end", "fact_headcount_monthly / dim_employee", "Department x month", "HR Analytics", "5"),
    ("M02", "Hires", "Employees hired during the month", "fact_headcount_monthly", "Department x month", "HR Analytics", "5"),
    ("M03", "Exits", "Employees leaving during the month", "fact_headcount_monthly", "Department x month", "HR Analytics", "5"),
    ("M04", "Attrition rate (monthly)", "Monthly exits / starting headcount x 100", "fact_headcount_monthly", "Department x month", "HR Analytics", "10"),
    ("M05", "Attrition rate (rolling 12 months)", "12-month exits / average ending headcount x 100", "fact_headcount_monthly", "Department x month", "HR Analytics", "10"),
    ("M06", "Voluntary attrition rate", "12-month voluntary exits / average ending headcount x 100", "fact_headcount_monthly", "Department x month", "HR Analytics", "10"),
    ("M07", "Gross pay", "Total earnings before deductions", "fact_payroll", "Employee x month", "Payroll", "5"),
    ("M08", "Net pay", "Take-home pay after deductions", "fact_payroll", "Employee x month", "Payroll", "5"),
    ("M09", "Payroll cost", "Gross pay plus employer PF and ESI", "fact_payroll", "Employee x month", "Finance", "5"),
    ("M10", "Cost per head", "Employer cost / distinct paid employees", "fact_payroll", "Department x month", "Finance", "5"),
    ("M11", "Overtime share", "Overtime pay / employer cost x 100", "fact_payroll", "Department x month", "Payroll", "5"),
    ("M12", "Variable pay share", "Variable pay / gross pay x 100", "fact_payroll", "Department x month", "Payroll", "5"),
    ("M13", "Attendance rate", "Present days adjusted for half days / scheduled days", "fact_attendance_monthly", "Department x month", "HR Analytics", "5"),
    ("M14", "Late arrival rate", "Late arrivals / present days", "fact_attendance_monthly", "Department x month", "HR Analytics", "5"),
    ("M15", "Leave without pay days", "Total unpaid absence days", "fact_payroll", "Employee x month", "Payroll", "5"),
    ("M16", "Revenue", "Negative ledger sum for accounts 4001-4004", "fact_ledger", "Account x month", "Finance", "n/a"),
    ("M17", "Net profit", "Revenue less expenses, including account 4900", "fact_ledger", "Month", "Finance", "n/a"),
    ("M18", "Operating margin", "Net profit / revenue x 100", "fact_ledger", "Month", "Finance", "n/a"),
    ("M19", "Payroll as % of revenue", "Ledger payroll cost / revenue x 100", "fact_payroll + fact_ledger", "Month", "Finance", "n/a"),
    ("M20", "Days sales outstanding", "Closing receivables / recent credit sales including GST x 90", "fact_invoice + fact_ledger", "Month", "Finance", "n/a"),
    ("M21", "Overdue receivables", "Unpaid invoice balances past due date", "fact_invoice", "Client x date", "Finance", "n/a"),
    ("M22", "Task completion rate", "Done tasks / non-cancelled tasks x 100", "fact_task", "Team x sprint", "Engineering Ops", "5 tasks"),
    ("M23", "On-time delivery rate", "On-time done tasks / done tasks x 100", "fact_task", "Team x sprint", "Engineering Ops", "5 tasks"),
    ("M24", "Velocity", "Story points for completed tasks", "fact_task", "Team x sprint", "Engineering Ops", "n/a"),
    ("M25", "Average cycle time", "Average days from task start to completion", "fact_task", "Team x sprint", "Engineering Ops", "5 tasks"),
    ("M26", "Anomaly flag rate", "Flagged records / scored records x 100", "fact_anomaly", "Source x month", "AI/ML", "n/a"),
    ("M27", "High-risk share", "High-risk employees / assessed employees x 100", "fact_attrition_risk", "Department", "AI/ML", "10"),
    ("M28", "Forecast error (MAPE)", "Average absolute percentage forecast error", "fact_forecast + fact_headcount_monthly", "Department x month", "AI/ML", "n/a"),
]

con = duckdb.connect(str(DB_PATH))

try:
    # Recreate only the metric dictionary, not warehouse tables.
    con.execute("DROP VIEW IF EXISTS metric_catalog")
    con.execute("DROP TABLE IF EXISTS metric_dictionary")

    con.execute("""
        CREATE TABLE metric_dictionary (
            metric_id VARCHAR,
            metric_name VARCHAR,
            definition VARCHAR,
            source VARCHAR,
            grain VARCHAR,
            owner VARCHAR,
            minimum_group_size VARCHAR
        )
    """)

    con.executemany(
        "INSERT INTO metric_dictionary VALUES (?, ?, ?, ?, ?, ?, ?)",
        METRICS,
    )

    con.execute("""
        CREATE VIEW metric_catalog AS
        SELECT *
        FROM metric_dictionary
        ORDER BY metric_id
    """)

    rows = con.execute("SELECT * FROM metric_catalog").fetchall()
    headers = [d[0] for d in con.description]

    with open(EVIDENCE_DIR / "metric_catalog_output.csv",
              "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    schema = con.execute("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'main'
        ORDER BY table_name, ordinal_position
    """).fetchall()

    with open(EVIDENCE_DIR / "warehouse_columns.csv",
              "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["table_name", "column_name", "data_type"])
        writer.writerows(schema)

    print("Metric catalog created successfully.")
    print(f"Catalog entries: {len(rows)} (expected 28)")
    print("Evidence files saved in the evidence folder.")

finally:
    con.close()
