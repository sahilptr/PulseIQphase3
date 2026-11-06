from pathlib import Path
import duckdb

BASE_DIR = Path(__file__).resolve().parent

database_files = [
    p for p in BASE_DIR.rglob("*.duckdb")
    if p.is_file()
]

print("\nDATABASE FILES FOUND:")
for p in database_files:
    print(p, "| bytes:", p.stat().st_size)

if not database_files:
    print("\nNo DuckDB database file found. Stop here.")
    raise SystemExit(1)

if len(database_files) > 1:
    print("\nMore than one database found. Use the correct existing database path.")
    raise SystemExit(1)

DB_PATH = database_files[0]

con = duckdb.connect(str(DB_PATH), read_only=True)

try:
    objects = con.execute("""
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_type, table_name
    """).fetchall()

    print("\nDATABASE OBJECTS:")
    for obj in objects:
        print(obj)

    print("\nOFFICIAL METRIC VIEW COLUMNS:")
    for name, object_type in objects:
        if name.startswith("metric_m") and object_type == "VIEW":
            print(f"\n{name}")
            columns = con.execute(
                f"DESCRIBE SELECT * FROM \"{name}\""
            ).fetchall()

            for col in columns:
                print(" ", col[0], col[1])

    for name in [
        "dim_employee",
        "dim_location",
        "fact_headcount_monthly",
        "metric_m01_headcount",
        "metric_m02_hires",
        "metric_m03_exits",
    ]:
        found = any(obj[0] == name for obj in objects)
        if found:
            print(f"\nSAMPLE: {name}")
            print(con.execute(
                f'SELECT * FROM "{name}" LIMIT 3'
            ).fetchdf().to_string(index=False))

finally:
    con.close()