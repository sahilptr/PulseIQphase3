
import duckdb

DB_PATH = r"D:\PulseIQ\pulseiq.duckdb"

con = duckdb.connect(DB_PATH, read_only=True)

print("\n--- ATTENDANCE TABLE ---")
print(con.execute("""
    DESCRIBE fact_attendance_monthly
""").fetchdf().to_string(index=False))

print("\n--- LEAVE TABLE ---")
print(con.execute("""
    DESCRIBE fact_leave
""").fetchdf().to_string(index=False))

print("\n--- DATE DIMENSION ---")
print(con.execute("""
    DESCRIBE dim_date
""").fetchdf().to_string(index=False))

print("\n--- METRIC VIEWS ---")
print(con.execute("""
    SELECT table_name
    FROM information_schema.views
    WHERE table_name LIKE 'metric_m%'
    ORDER BY table_name
""").fetchdf().to_string(index=False))

con.close()
