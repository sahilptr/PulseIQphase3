
from pathlib import Path
import duckdb
import pandas as pd
import numpy as np

BASE = Path(__file__).resolve().parent
DB = BASE / "pulseiq.duckdb"
OUT = BASE / "task13_evidence"
OUT.mkdir(exist_ok=True)

con = duckdb.connect(str(DB))

def read_table(name):
    return con.execute(f"SELECT * FROM {name}").df()

# Load source tables
headcount = read_table("fact_headcount_monthly")
payroll = read_table("fact_payroll")
attendance = read_table("fact_attendance_monthly")
leave = read_table("fact_leave")
departments = read_table("dim_department")

# Standardize month fields
headcount["month_start_date"] = pd.to_datetime(
    headcount["month_start_date"]
).dt.to_period("M").dt.to_timestamp()

payroll["month_start_date"] = (
    pd.to_datetime(payroll["period_end_date"])
    .dt.to_period("M").dt.to_timestamp()
)

attendance["month_start_date"] = (
    pd.to_datetime(attendance["period_end_date"])
    .dt.to_period("M").dt.to_timestamp()
)

leave["start_date"] = pd.to_datetime(leave["start_date"], errors="coerce")
leave["month_start_date"] = (
    leave["start_date"].dt.to_period("M").dt.to_timestamp()
)

# 1. Headcount and actual attrition by department/month
hc = (
    headcount.groupby(["department_id", "month_start_date"], as_index=False)
    .agg(
        headcount_start=("headcount_start", "max"),
        hires=("hires", "sum"),
        exits=("exits", "sum"),
        voluntary_exits=("voluntary_exits", "sum"),
        headcount_end=("headcount_end", "max"),
        attrition_rate_monthly_pct=("attrition_rate_monthly_pct", "mean"),
    )
)

# 2. Payroll totals by department/month
pay = (
    payroll.groupby(["department_id", "month_start_date"], as_index=False)
    .agg(
        payroll_employer_cost=("employer_cost", "sum"),
        gross_pay=("gross_pay", "sum"),
        overtime_cost=("overtime_pay", "sum"),
        payroll_overtime_hours=("overtime_hours_paid", "sum"),
        payroll_rows=("payroll_item_id", "count"),
    )
)

# 3. Attendance totals by department/month
att = (
    attendance.groupby(["department_id", "month_start_date"], as_index=False)
    .agg(
        scheduled_days=("scheduled_days", "sum"),
        present_days=("present_days", "sum"),
        attendance_overtime_hours=("overtime_hours", "sum"),
        attendance_rate=("attendance_rate", "mean"),
        late_arrivals=("late_arrivals", "sum"),
        attendance_employees=("employee_id", "nunique"),
    )
)

# 4. Approved leave by employee and start month.
# Assign each employee to the department recorded in attendance
# for that same month.
leave["status_clean"] = leave["status"].astype(str).str.strip().str.lower()
approved_leave = leave[leave["status_clean"] == "approved"].copy()

employee_department = attendance[
    ["employee_id", "department_id", "month_start_date"]
].drop_duplicates()

leave_with_department = approved_leave.merge(
    employee_department,
    on=["employee_id", "month_start_date"],
    how="left",
)

# Fallback to payroll department if attendance mapping is missing
pay_employee = payroll[
    ["employee_id", "department_id", "month_start_date"]
].drop_duplicates()

missing_dept = leave_with_department["department_id"].isna()
if missing_dept.any():
    fallback = approved_leave.loc[missing_dept, [
        "employee_id", "month_start_date", "days"
    ]].merge(
        pay_employee,
        on=["employee_id", "month_start_date"],
        how="left",
    )
    leave_with_department.loc[missing_dept, "department_id"] = (
        fallback["department_id"].values
    )

leave_monthly = (
    leave_with_department.dropna(subset=["department_id"])
    .groupby(["department_id", "month_start_date"], as_index=False)
    .agg(
        approved_leave_days=("days", "sum"),
        approved_leave_requests=("leave_request_id", "nunique"),
    )
)

# Join only after each source has been aggregated to the same grain
combined = (
    hc.merge(pay, on=["department_id", "month_start_date"], how="outer")
      .merge(att, on=["department_id", "month_start_date"], how="outer")
      .merge(leave_monthly, on=["department_id", "month_start_date"], how="left")
      .merge(departments, on="department_id", how="left")
)

numeric_cols = [
    "headcount_start", "hires", "exits", "voluntary_exits", "headcount_end",
    "attrition_rate_monthly_pct", "payroll_employer_cost", "gross_pay",
    "overtime_cost", "payroll_overtime_hours", "payroll_rows",
    "scheduled_days", "present_days", "attendance_overtime_hours",
    "attendance_rate", "late_arrivals", "attendance_employees",
    "approved_leave_days", "approved_leave_requests",
]

for col in numeric_cols:
    if col in combined.columns:
        combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0)

combined["department_name"] = combined["department_name"].fillna(
    combined["department_id"]
)

# Per-head measures
combined["cost_per_head"] = np.where(
    combined["headcount_end"] > 0,
    combined["payroll_employer_cost"] / combined["headcount_end"],
    np.nan,
)

combined["leave_days_per_head"] = np.where(
    combined["headcount_end"] > 0,
    combined["approved_leave_days"] / combined["headcount_end"],
    np.nan,
)

combined["overtime_hours"] = combined[
    "attendance_overtime_hours"
].fillna(0)

combined["overtime_hours_per_head"] = np.where(
    combined["headcount_end"] > 0,
    combined["overtime_hours"] / combined["headcount_end"],
    np.nan,
)

# Save combined table and source-level evidence
combined = combined.sort_values(["month_start_date", "department_id"])
combined.to_csv(OUT / "task13_department_month.csv", index=False)

hc.to_csv(OUT / "headcount_monthly_aggregate.csv", index=False)
pay.to_csv(OUT / "payroll_monthly_aggregate.csv", index=False)
att.to_csv(OUT / "attendance_monthly_aggregate.csv", index=False)
leave_monthly.to_csv(OUT / "leave_monthly_aggregate.csv", index=False)

# Store the final result in DuckDB
con.execute("DROP TABLE IF EXISTS task13_department_month")
con.register("combined_df", combined)
con.execute("""
    CREATE TABLE task13_department_month AS
    SELECT * FROM combined_df
""")
con.unregister("combined_df")

# Check whether the reference table is already in DuckDB
db_tables = con.execute("SHOW TABLES").df()["name"].tolist()
reference = None

for table_name in db_tables:
    if table_name.lower() == "reference_summary_dept_month":
        reference = con.execute(
            f'SELECT * FROM "{table_name}"'
        ).df()
        break

# Otherwise search the validation vault for a CSV or Excel reference file
if reference is None:
    vault = BASE / "04_Validation_Vault"
    candidates = []

    if vault.exists():
        for path in vault.rglob("*"):
            if path.is_file() and "reference_summary_dept_month" in path.stem.lower():
                if path.suffix.lower() == ".csv":
                    candidates.append(path)
                elif path.suffix.lower() in [".xlsx", ".xls"]:
                    candidates.append(path)

    if candidates:
        ref_path = candidates[0]
        print(f"\nReference file found: {ref_path}")
        if ref_path.suffix.lower() == ".csv":
            reference = pd.read_csv(ref_path)
        else:
            reference = pd.read_excel(ref_path)

# Save reference and prepare a comparison if possible
if reference is not None:
    reference.to_csv(OUT / "reference_summary_dept_month.csv", index=False)

    print("\nREFERENCE COLUMNS:")
    print(reference.columns.tolist())

    print("\nREFERENCE SAMPLE:")
    print(reference.head(5).to_string(index=False))

    # Normalize column names to make common naming variations easier to match
    def normalize_columns(df):
        df = df.copy()
        df.columns = [
            str(c).strip().lower().replace(" ", "_").replace("-", "_")
            for c in df.columns
        ]
        return df

    ref = normalize_columns(reference)
    actual = normalize_columns(combined)

    aliases = {
        "department_id": ["department_id", "dept_id"],
        "month_start_date": ["month_start_date", "month", "period", "period_month"],
        "headcount_end": ["headcount_end", "ending_headcount", "headcount"],
        "payroll_employer_cost": ["payroll_employer_cost", "employer_cost", "payroll_cost"],
        "exits": ["exits", "exit_count"],
        "attrition_rate_monthly_pct": [
            "attrition_rate_monthly_pct", "attrition_rate", "monthly_attrition_pct"
        ],
        "overtime_hours": ["overtime_hours", "attendance_overtime_hours"],
        "approved_leave_days": ["approved_leave_days", "leave_days"],
    }

    def find_column(df, choices):
        for choice in choices:
            if choice in df.columns:
                return choice
        return None

    join_cols = {}
    for target, choices in aliases.items():
        ref_col = find_column(ref, choices)
        actual_col = find_column(actual, choices)
        if ref_col and actual_col:
            join_cols[target] = (ref_col, actual_col)

    if "department_id" in join_cols and "month_start_date" in join_cols:
        ref_dept_col, _ = join_cols["department_id"]
        ref_month_col, _ = join_cols["month_start_date"]
        _, actual_month_col = join_cols["month_start_date"]

        ref["department_id"] = ref[ref_dept_col].astype(str)
        ref["month_start_date"] = pd.to_datetime(
            ref[ref_month_col], errors="coerce"
        ).dt.to_period("M").dt.to_timestamp()

        actual_for_compare = actual.copy()
        actual_for_compare["department_id"] = actual_for_compare[
            "department_id"
        ].astype(str)
        actual_for_compare["month_start_date"] = pd.to_datetime(
            actual_for_compare[actual_month_col], errors="coerce"
        ).dt.to_period("M").dt.to_timestamp()

        comparison = ref[["department_id", "month_start_date"]].merge(
            actual_for_compare,
            on=["department_id", "month_start_date"],
            how="outer",
            suffixes=("_reference", "_actual"),
        )

        # Add reference numeric values and calculate differences where possible
        for target, (ref_col, actual_col) in join_cols.items():
            if target in ["department_id", "month_start_date"]:
                continue

            ref_values = ref[
                ["department_id", "month_start_date", ref_col]
            ].rename(columns={ref_col: f"{target}_reference"})

            comparison = comparison.merge(
                ref_values,
                on=["department_id", "month_start_date"],
                how="left",
            )

            actual_name = target
            if actual_name in comparison.columns:
                comparison[f"{target}_difference"] = (
                    pd.to_numeric(comparison[actual_name], errors="coerce")
                    - pd.to_numeric(
                        comparison[f"{target}_reference"], errors="coerce"
                    )
                )

        comparison.to_csv(OUT / "task13_reference_comparison.csv", index=False)
        print("\nREFERENCE COMPARISON SAVED.")
    else:
        print(
            "\nCould not automatically match reference department/month columns. "
            "Reference file was saved for inspection."
        )
else:
    print(
        "\nREFERENCE FILE NOT FOUND. The combined department/month table "
        "was still created. Put the reference file inside "
        "04_Validation_Vault and rerun this script."
    )

con.close()

print("\nTASK 13 BUILD COMPLETE")
print("Final rows:", len(combined))
print("Departments:", combined["department_id"].nunique())
print("Months:", combined["month_start_date"].nunique())
print("Evidence folder:", OUT)
print("\nFINAL TABLE SAMPLE:")
print(combined.head(10).to_string(index=False))