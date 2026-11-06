
from pathlib import Path
import duckdb

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "pulseiq.duckdb"

DIMENSIONS = [
    "account", "client", "date", "department", "employee",
    "leave_type", "location", "role", "sprint", "team", "vendor"
]

FACTS = [
    "anomaly", "attendance_monthly", "attrition_risk", "expense",
    "forecast", "headcount_monthly", "invoice", "invoice_payment",
    "leave", "ledger", "payroll", "task"
]

def main():
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    con = duckdb.connect(str(DB_PATH))

    try:
        raw_tables = {
            row[0] for row in con.execute("SHOW TABLES").fetchall()
        }

        print("Rebuilding dimension and fact tables...")

        for name in DIMENSIONS:
            source = f"raw_dim_{name}"
            target = f"dim_{name}"

            if source not in raw_tables:
                raise RuntimeError(f"Missing source table: {source}")

            con.execute(
                f'CREATE OR REPLACE TABLE "{target}" AS '
                f'SELECT * FROM "{source}"'
            )
            count = con.execute(
                f'SELECT COUNT(*) FROM "{target}"'
            ).fetchone()[0]
            print(f"Created {target}: {count} rows")

        for name in FACTS:
            source = f"raw_fact_{name}"
            target = f"fact_{name}"

            if source not in raw_tables:
                raise RuntimeError(f"Missing source table: {source}")

            con.execute(
                f'CREATE OR REPLACE TABLE "{target}" AS '
                f'SELECT * FROM "{source}"'
            )
            count = con.execute(
                f'SELECT COUNT(*) FROM "{target}"'
            ).fetchone()[0]
            print(f"Created {target}: {count} rows")

        print("\nWarehouse table creation completed.")
        print("Note: this restores the source tables under warehouse names.")
        print("It does not independently validate surrogate keys or orphans.")

    finally:
        con.close()

if __name__ == "__main__":
    main()
