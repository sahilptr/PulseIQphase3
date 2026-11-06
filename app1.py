from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="PulseIQ Workforce",
    page_icon="📊",
    layout="wide",
)

BASE_DIR = Path(__file__).resolve().parent

st.title("PulseIQ | Workforce Overview")
st.caption("Workforce trends using governed PulseIQ metrics")

# Locate the existing database file.
db_files = [
    p for p in BASE_DIR.rglob("*.duckdb")
    if p.is_file()
]

if len(db_files) != 1:
    st.error(
        "Expected exactly one DuckDB database file. "
        "Run inspect_dashboard_data.py and resolve the database path."
    )
    st.stop()

DB_PATH = db_files[0]


@st.cache_data(ttl=60)
def load_metric(view_name):
    allowed_views = {
        "metric_m01_headcount",
        "metric_m02_hires",
        "metric_m03_exits",
    }

    if view_name not in allowed_views:
        raise ValueError("Unapproved metric view")

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        return con.execute(
            f'SELECT * FROM "{view_name}"'
        ).fetchdf()


try:
    headcount = load_metric("metric_m01_headcount")
    hires = load_metric("metric_m02_hires")
    exits = load_metric("metric_m03_exits")
except Exception as exc:
    st.error(f"Could not load official metrics: {exc}")
    st.stop()

required = {"period", "department_id", "metric_value"}

for name, df in [
    ("Headcount", headcount),
    ("Hires", hires),
    ("Exits", exits),
]:
    if not required.issubset(df.columns):
        st.error(f"{name} metric view has an unexpected schema.")
        st.stop()

for df in [headcount, hires, exits]:
    df["period"] = pd.to_datetime(df["period"], errors="coerce")

headcount = headcount.dropna(subset=["period"])
hires = hires.dropna(subset=["period"])
exits = exits.dropna(subset=["period"])

if headcount.empty:
    st.warning("No headcount metric data is available.")
    st.stop()

# Filters
st.sidebar.header("Dashboard Filters")

departments = sorted(
    headcount["department_id"].dropna().astype(str).unique()
)

selected_departments = st.sidebar.multiselect(
    "Department",
    departments,
    default=departments,
)

min_date = headcount["period"].min().date()
max_date = headcount["period"].max().date()

date_range = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

if not isinstance(date_range, (tuple, list)) or len(date_range) != 2:
    st.info("Select a start date and an end date.")
    st.stop()

start_date, end_date = date_range

def filtered(df):
    return df[
        df["department_id"].astype(str).isin(selected_departments)
        & df["period"].dt.date.between(start_date, end_date)
    ].copy()

hc = filtered(headcount)
hi = filtered(hires)
ex = filtered(exits)

# KPI cards
latest_period = hc["period"].max()
latest = hc[hc["period"] == latest_period]

# Do not interpret a suppressed department as zero.
if latest["metric_value"].isna().any():
    st.warning(
        "Some department values are suppressed. "
        "A trustworthy company-wide headcount KPI requires "
        "an approved organisation-level metric."
    )

kpi_headcount = latest["metric_value"].sum(min_count=1)
kpi_hires = hi.loc[hi["period"] == hi["period"].max(), "metric_value"].sum(min_count=1)
kpi_exits = ex.loc[ex["period"] == ex["period"].max(), "metric_value"].sum(min_count=1)

c1, c2, c3 = st.columns(3)

c1.metric(
    "Latest reported headcount",
    "Suppressed" if pd.isna(kpi_headcount) else f"{kpi_headcount:,.0f}",
)

c2.metric(
    "Hires in latest available month",
    "N/A" if pd.isna(kpi_hires) else f"{kpi_hires:,.0f}",
)

c3.metric(
    "Exits in latest available month",
    "N/A" if pd.isna(kpi_exits) else f"{kpi_exits:,.0f}",
)

# Headcount trend
st.subheader("Headcount trend")

trend = (
    hc.groupby("period", as_index=False)["metric_value"]
    .sum(min_count=1)
    .sort_values("period")
)

fig = px.line(
    trend,
    x="period",
    y="metric_value",
    markers=True,
    labels={
        "period": "Month",
        "metric_value": "Reported headcount",
    },
)

fig.update_layout(showlegend=False)
st.plotly_chart(fig, use_container_width=True)

valid_trend = trend.dropna(subset=["metric_value"])

if not valid_trend.empty:
    first = valid_trend.iloc[0]
    last = valid_trend.iloc[-1]
    change = last["metric_value"] - first["metric_value"]

    st.caption(
        f"Insight: reported headcount changed by {change:+,.0f} "
        f"between {first['period']:%b %Y} and {last['period']:%b %Y}. "
        "Suppressed groups may affect totals."
    )

# Department breakdown
st.subheader("Department workforce breakdown")

dept = (
    latest.groupby("department_id", as_index=False)["metric_value"]
    .sum(min_count=1)
    .dropna(subset=["metric_value"])
    .sort_values("metric_value", ascending=False)
)

if not dept.empty:
    fig = px.bar(
        dept,
        x="department_id",
        y="metric_value",
        labels={
            "department_id": "Department",
            "metric_value": "Reported headcount",
        },
    )
    st.plotly_chart(fig, use_container_width=True)

    top = dept.iloc[0]
    st.caption(
        f"Insight: {top['department_id']} has the largest "
        f"reported department headcount ({top['metric_value']:,.0f})."
    )
else:
    st.info("No unsuppressed department values are available.")

st.divider()

st.subheader("Next: Location tier and work mode")

st.info(
    "These charts will be enabled after the actual location and "
    "work-mode columns are verified and exposed through governed "
    "metric views. The app will not query raw tables to fill the gap."
)

st.caption("PulseIQ | Workforce Analytics")