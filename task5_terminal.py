
from pathlib import Path
import duckdb

DB_PATH = Path(r"D:\PulseIQ\pulseiq.duckdb")

def main():
    if not DB_PATH.is_file():
        print(f"ERROR: Database file not found: {DB_PATH}")
        return

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        tables = {
            row[0]
            for row in con.execute("SHOW TABLES").fetchall()
        }

        print("\n========== PULSEIQ TASK 5 DASHBOARD ==========")
        print(f"Database: {DB_PATH}")
        print(f"Total tables/views: {len(tables)}")

        print("\n========== DATABASE STATUS ==========")
        print("Raw tables:", sum(t.startswith("raw_") for t in tables))
        print("Dimension tables:", sum(t.startswith("dim_") for t in tables))
        print("Fact tables:", sum(t.startswith("fact_") for t in tables))

        required = [
            "metric_m01_headcount",
            "metric_m02_hires",
            "metric_m03_exits",
        ]

        print("\n========== OFFICIAL METRIC STATUS ==========")
        for name in required:
            print(f"{name}: {'AVAILABLE' if name in tables else 'MISSING'}")

        if "metric_m01_headcount" not in tables:
            print("\nDashboard metrics cannot run yet.")
            print("The warehouse and official metric views must be rebuilt first.")
            print("Raw data is present, but raw tables are not official metrics.")
            return

        print("\n========== HEADCOUNT METRIC ==========")
        result = con.execute(
            'SELECT * FROM "metric_m01_headcount" LIMIT 20'
        )
        print("Columns:", [d[0] for d in result.description])
        for row in result.fetchall():
            print(row)

        print("\n========== HIRES METRIC ==========")
        if "metric_m02_hires" in tables:
            result = con.execute(
                'SELECT * FROM "metric_m02_hires" LIMIT 20'
            )
            print("Columns:", [d[0] for d in result.description])
            for row in result.fetchall():
                print(row)

        print("\n========== EXITS METRIC ==========")
        if "metric_m03_exits" in tables:
            result = con.execute(
                'SELECT * FROM "metric_m03_exits" LIMIT 20'
            )
            print("Columns:", [d[0] for d in result.description])
            for row in result.fetchall():
                print(row)

        print("\nDashboard output completed.")

    finally:
        con.close()


if __name__ == "__main__":
    main()
