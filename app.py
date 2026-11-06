from pathlib import Path
import duckdb
import pandas as pd
import streamlit as st
import plotly.express as px

# PulseIQ Task 5 CEO Dashboard
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "pulseiq.duckdb"

st.set_page_config(page_title="PulseIQ CEO Dashboard", page_icon="📊", layout="wide")
st.title("PulseIQ | CEO Dashboard")
st.caption("Workforce overview • Interactive department and date filters")

if not DB_PATH.is_file():
    st.error(f"Database file not found: {DB_PATH}. Save this file in D:\\PulseIQ beside pulseiq.duckdb.")
    st.stop()

@st.cache_resource
def get_connection(path):
    return duckdb.connect(path, read_only=True)

con = get_connection(str(DB_PATH))

def quote_ident(value):
    return '"' + str(value).replace('"', '""') + '"'

def table_names():
    return [r[0] for r in con.execute("SHOW TABLES").fetchall()]

def table_columns(table):
    return [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {quote_ident(table)}").fetchall()]

def find_col(columns, candidates):
    lookup = {str(c).lower(): c for c in columns}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    for candidate in candidates:
        for col in columns:
            if candidate.lower() in str(col).lower():
                return col
    return None

tables = table_names()
head_table = "fact_headcount_monthly" if "fact_headcount_monthly" in tables else None
if head_table is None:
    st.error("The required fact_headcount_monthly table is missing. Task 2 warehouse tables must be restored before this dashboard can run.")
    st.stop()

head_cols = table_columns(head_table)
date_col = find_col(head_cols, ["month_start_date", "period", "month", "date"])
dept_col = find_col(head_cols, ["department_id", "department"])
end_col = find_col(head_cols, ["headcount_end", "ending_headcount", "headcount"])
start_col = find_col(head_cols, ["headcount_start", "starting_headcount"])
hires_col = find_col(head_cols, ["hires", "hire_count"])
exits_col = find_col(head_cols, ["exits", "exit_count"])
attr_col = find_col(head_cols, ["attrition_rate_monthly_pct", "monthly_attrition", "attrition_rate"])

if not date_col or not dept_col:
    st.error(f"Could not identify date and department columns. Columns found: {head_cols}")
    st.stop()

hc = con.execute(f"SELECT * FROM {quote_ident(head_table)}").df()
hc[date_col] = pd.to_datetime(hc[date_col], errors="coerce")
hc = hc.dropna(subset=[date_col]).copy()
if hc.empty:
    st.error("No usable dates were found in fact_headcount_monthly.")
    st.stop()

for c in [end_col, start_col, hires_col, exits_col, attr_col]:
    if c:
        hc[c] = pd.to_numeric(hc[c], errors="coerce")

hc["__month"] = hc[date_col].dt.to_period("M").astype(str)
min_date, max_date = hc[date_col].min().date(), hc[date_col].max().date()
departments = sorted(hc[dept_col].dropna().astype(str).unique().tolist())

st.sidebar.header("Filters")
selected_depts = st.sidebar.multiselect("Department", departments, default=departments)
picked_dates = st.sidebar.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
if isinstance(picked_dates, (tuple, list)) and len(picked_dates) == 2:
    date_start, date_end = picked_dates
elif isinstance(picked_dates, (tuple, list)) and len(picked_dates) == 1:
    date_start = date_end = picked_dates[0]
else:
    date_start, date_end = min_date, max_date

filtered = hc[
    hc[dept_col].astype(str).isin(selected_depts)
    & hc[date_col].dt.date.between(date_start, date_end)
].copy()

if filtered.empty:
    st.warning("No records match these filters. Select another department or date range.")
    st.stop()

latest_date = filtered[date_col].max()
latest = filtered[filtered[date_col] == latest_date]
headcount = float(latest[end_col].sum()) if end_col else float("nan")
hires = float(filtered[hires_col].sum()) if hires_col else float("nan")
exits = float(filtered[exits_col].sum()) if exits_col else float("nan")
if start_col and exits_col:
    total_start = float(filtered[start_col].sum())
    exit_rate = exits / total_start * 100 if total_start else float("nan")
elif attr_col:
    exit_rate = float(filtered[attr_col].mean())
else:
    exit_rate = float("nan")

def number(v):
    return "N/A" if pd.isna(v) else f"{v:,.0f}"

def percent(v):
    return "N/A" if pd.isna(v) else f"{v:.2f}%"

k1, k2, k3, k4 = st.columns(4)
k1.metric("Headcount (latest selected month)", number(headcount))
k2.metric("Hires (selected period)", number(hires))
k3.metric("Exits (selected period)", number(exits))
k4.metric("Exit-rate proxy", percent(exit_rate))
st.caption(f"Selected period: {date_start} to {date_end} | Latest month represented: {latest_date:%Y-%m}")

BLUE = "#2563EB"
TEAL = "#0F766E"
ORANGE = "#EA580C"

# Chart 1: month-end headcount trend
st.subheader("1. Headcount trend")
if end_col:
    trend = filtered.groupby("__month", as_index=False)[end_col].sum().sort_values("__month")
    fig = px.line(trend, x="__month", y=end_col, markers=True, title="Month-end headcount")
    fig.update_traces(line_color=BLUE, marker_color=BLUE)
    fig.update_layout(xaxis_title="Month", yaxis_title="Employees", showlegend=False)
    st.plotly_chart(fig, width="stretch")
    if len(trend) >= 2:
        first, last = float(trend.iloc[0][end_col]), float(trend.iloc[-1][end_col])
        change = last - first
        action = "increased" if change > 0 else "decreased" if change < 0 else "was unchanged"
        st.info(f"Insight: Headcount {action} by {abs(change):,.0f}, from {first:,.0f} in {trend.iloc[0]['__month']} to {last:,.0f} in {trend.iloc[-1]['__month']}.")
    else:
        st.info(f"Insight: Headcount in the selected month is {float(trend.iloc[-1][end_col]):,.0f}.")
else:
    st.warning("Headcount trend unavailable: no headcount-end column was detected.")

# Chart 2: department comparison at the latest selected month
st.subheader("2. Department breakdown")
if end_col:
    dept_data = latest.groupby(dept_col, as_index=False)[end_col].sum().sort_values(end_col, ascending=False)
    fig = px.bar(dept_data, x=dept_col, y=end_col, title="Headcount by department (latest selected month)", color_discrete_sequence=[TEAL])
    fig.update_layout(xaxis_title="Department", yaxis_title="Employees", showlegend=False)
    st.plotly_chart(fig, width="stretch")
    if not dept_data.empty:
        top = dept_data.iloc[0]
        total = float(dept_data[end_col].sum())
        share = float(top[end_col]) / total * 100 if total else 0
        st.info(f"Insight: {top[dept_col]} is the largest department with {float(top[end_col]):,.0f} employees ({share:.1f}% of selected headcount).")
else:
    dept_data = pd.DataFrame()
    st.warning("Department breakdown unavailable: no headcount-end column was detected.")

# Employee dimension is used for location/work mode distributions.
# Employee dimension is used for location/work mode distributions.
emp_table = "dim_employee" if "dim_employee" in tables else (
    "raw_dim_employee" if "raw_dim_employee" in tables else None
)

emp = pd.DataFrame()
loc_col = mode_col = emp_dept_col = None

if emp_table:
    emp = con.execute(
        f"SELECT * FROM {quote_ident(emp_table)}"
    ).df()

if emp is None:
    emp = pd.DataFrame()

emp_cols = list(emp.columns)

if not emp.empty:
    loc_col = find_col(
        emp_cols,
        ["location_tier", "locationtier", "tier", "location_category", "location_type"]
    )
    mode_col = find_col(
        emp_cols,
        ["work_mode", "workmode", "work_arrangement", "work_type"]
    )
    emp_dept_col = find_col(emp_cols, ["department_id", "department"])
    loc_col = find_col(emp_cols, ["location_tier", "locationtier", "tier", "location_category", "location_type"])
    mode_col = find_col(emp_cols, ["work_mode", "workmode", "work_arrangement", "work_type"])
    emp_dept_col = find_col(emp_cols, ["department_id", "department"])
    current_col = find_col(emp_cols, ["is_current", "current_flag"])
    if current_col:
        current_values = emp[current_col].astype(str).str.lower()
        emp = emp[current_values.isin(["true", "1", "yes"])].copy()
    if emp_dept_col:
        emp = emp[emp[emp_dept_col].astype(str).isin(selected_depts)].copy()

    # Location tier often lives in dim_location rather than dim_employee; join it when needed.
    if not loc_col and "dim_location" in tables:
        location_dimension = con.execute(f"SELECT * FROM {quote_ident('dim_location')}").df()
        location_cols = list(location_dimension.columns)
        loc_dim_tier = find_col(location_cols, ["location_tier", "locationtier", "tier", "location_category", "location_type"])
        emp_location_key = find_col(emp_cols, ["location_id", "location_key"])
        dim_location_key = find_col(location_cols, ["location_id", "location_key"])
        if loc_dim_tier and emp_location_key and dim_location_key:
            location_dimension = location_dimension[[dim_location_key, loc_dim_tier]].drop_duplicates()
            emp = emp.merge(location_dimension, left_on=emp_location_key, right_on=dim_location_key, how="left")
            loc_col = loc_dim_tier

st.subheader("3. Employee distribution by location tier")
if loc_col and not emp.empty:
    location_data = emp[loc_col].fillna("Unknown").astype(str).value_counts().rename_axis("Location tier").reset_index(name="Employees")
    fig = px.bar(location_data, x="Location tier", y="Employees", title="Employee records by location tier", color_discrete_sequence=[ORANGE])
    fig.update_layout(xaxis_title="Location tier", yaxis_title="Employee records", showlegend=False)
    st.plotly_chart(fig, width="stretch")
    top = location_data.iloc[0]
    total = int(location_data["Employees"].sum())
    st.info(f"Insight: {top['Location tier']} is the largest location tier with {int(top['Employees']):,} employee records ({top['Employees']/total*100:.1f}% of the displayed distribution).")
else:
    st.warning("Location-tier chart cannot be drawn because no recognizable location-tier field was found in the employee table.")
    st.caption(f"Table checked: {emp_table or 'not found'} | Columns found: {list(emp.columns)}")

st.subheader("4. Employee distribution by work mode")
if mode_col and not emp.empty:
    mode_data = emp[mode_col].fillna("Unknown").astype(str).value_counts().rename_axis("Work mode").reset_index(name="Employees")
    fig = px.bar(mode_data, x="Work mode", y="Employees", title="Employee records by work mode", color_discrete_sequence=[BLUE])
    fig.update_layout(xaxis_title="Work mode", yaxis_title="Employee records", showlegend=False)
    st.plotly_chart(fig, width="stretch")
    top = mode_data.iloc[0]
    total = int(mode_data["Employees"].sum())
    st.info(f"Insight: {top['Work mode']} is the most common work mode with {int(top['Employees']):,} employee records ({top['Employees']/total*100:.1f}% of the displayed distribution).")
else:
    st.warning("Work-mode chart cannot be drawn because no recognizable work-mode field was found in the employee table.")
    st.caption(f"Table checked: {emp_table or 'not found'} | Columns found: {list(emp.columns)}")

st.divider()
st.header("Five CEO questions")
st.markdown("**1. How many employees do we have?**")
st.write(f"The latest selected month ({latest_date:%Y-%m}) has **{number(headcount)} employees** across the selected departments.")

st.markdown("**2. Are we growing or shrinking?**")
if pd.isna(hires) or pd.isna(exits):
    st.write("Cannot calculate net movement because hires or exits are unavailable.")
else:
    net = hires - exits
    description = "net growth" if net > 0 else "net decline" if net < 0 else "no net change"
    st.write(f"The selected period has **{number(hires)} hires** and **{number(exits)} exits**, giving **{description} of {abs(net):,.0f} employees**.")

st.markdown("**3. Which department has the most employees?**")
if end_col and not latest.empty:
    ranking = latest.groupby(dept_col)[end_col].sum().sort_values(ascending=False)
    st.write(f"**{ranking.index[0]}** leads in {latest_date:%Y-%m} with **{number(float(ranking.iloc[0]))} employees**.")
else:
    st.write("Cannot answer because headcount values are unavailable.")

st.markdown("**4. What is our exit/attrition pressure?**")
st.write(f"The selected period contains **{number(exits)} exits**. The calculated exit-rate proxy is **{percent(exit_rate)}** (selected-period exits divided by summed monthly starting headcount where available). This is not annualized.")

st.markdown("**5. What is the most common work arrangement?**")
if mode_col and not emp.empty:
    mode_counts = emp[mode_col].fillna("Unknown").astype(str).value_counts()
    st.write(f"**{mode_counts.index[0]}** is the most common displayed work mode with **{int(mode_counts.iloc[0]):,} employee records**.")
else:
    st.write("A work-mode field was not found, so this answer needs the employee table's actual work-mode column.")

with st.expander("Data notes and schema checks"):
    st.write(f"Database: {DB_PATH}")
    st.write(f"Headcount source: {head_table}")
    st.write(f"Headcount columns: {head_cols}")
    st.write(f"Employee source: {emp_table or 'not found'}")
    st.write(f"Employee columns: {list(emp.columns)}")
    st.write("Headcount charts and CEO answers use the active filters. Location/work-mode charts use the department filter and current employee dimension where an is_current field exists. Their counts are employee records, not historical month-end counts.")
