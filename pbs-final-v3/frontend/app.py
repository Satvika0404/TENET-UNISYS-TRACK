import os
import time
from datetime import datetime

import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# ---------------- Config ----------------
BACKEND = os.getenv("PBS_BACKEND", "http://127.0.0.1:8000").rstrip("/")

st.set_page_config(
    page_title="PBS Final v3 Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------- Style ----------------
st.markdown(
    """
<style>
:root{
  --bg: #0b1220;
  --card: rgba(255,255,255,0.045);
  --card2: rgba(0,0,0,0.35);
  --border: rgba(255,255,255,0.12);
  --muted: rgba(255,255,255,0.70);
  --muted2: rgba(255,255,255,0.55);
}

.block-container{ padding-top: 1.2rem; }
[data-testid="stSidebar"]{ background: radial-gradient(1200px 600px at 20% 0%, rgba(130,87,229,.18), transparent 70%); }

.section-box{
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 16px 16px 12px 16px;
  box-shadow: 0 12px 32px rgba(0,0,0,0.35);
  margin-bottom: 14px;
}

.section-title{
  font-size: 1.08rem;
  font-weight: 900;
  letter-spacing: 0.2px;
  margin-bottom: 2px;
}

.section-sub{
  color: var(--muted2);
  font-size: 0.92rem;
  margin-bottom: 10px;
}

.kpi-row{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 10px 0 12px 0;
}

.kpi{
  background: var(--card2);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 10px 12px;
}

.kpi-label{
  font-size: 0.82rem;
  color: var(--muted2);
}

.kpi-value{
  font-size: 1.35rem;
  font-weight: 950;
  margin-top: 2px;
}

.pulse{
  display:inline-block;
  width:10px;height:10px;border-radius:999px;
  background:#2ee59d;
  margin-right:8px;
  box-shadow: 0 0 0 0 rgba(46,229,157,.55);
  animation: pulse 1.6s ease-out infinite;
}
@keyframes pulse{
  0%{box-shadow:0 0 0 0 rgba(46,229,157,.55)}
  70%{box-shadow:0 0 0 14px rgba(46,229,157,0)}
  100%{box-shadow:0 0 0 0 rgba(46,229,157,0)}
}

.badge{
  display:inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,0.06);
  font-size: 0.82rem;
  color: rgba(255,255,255,0.82);
  margin-right: 6px;
  margin-bottom: 6px;
}

.small-note{
  color: var(--muted2);
  font-size: 0.86rem;
}

</style>
""",
    unsafe_allow_html=True,
)

# ---------------- Helpers ----------------
def normalize_list(payload):
    """Accepts list OR dict wrappers like {value: [...]} and returns a list."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if "value" in payload and isinstance(payload["value"], list):
            return payload["value"]
        if "items" in payload and isinstance(payload["items"], list):
            return payload["items"]
        # Sometimes API returns {"data": [...]}
        if "data" in payload and isinstance(payload["data"], list):
            return payload["data"]
    return []


def safe_get(path: str, timeout: float = 5.0):
    r = requests.get(f"{BACKEND}{path}", timeout=timeout)
    r.raise_for_status()
    return r.json()


def safe_post(path: str, payload: dict, timeout: float = 8.0):
    r = requests.post(f"{BACKEND}{path}", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def clean_resources_df(resources: list[dict]) -> pd.DataFrame:
    rows = []
    for rr in resources:
        t = rr.get("last", {})
        rows.append(
            {
                "Resource": rr.get("resource_id"),
                "Type": (rr.get("resource_type") or "").title(),
                "Time": t.get("ts"),
                "CPU": float(t.get("cpu_util", 0.0)),
                "Memory": float(t.get("mem_util", 0.0)),
                "GPU": float(t.get("gpu_util", 0.0)),
                "RTT (ms)": float(t.get("net_rtt_ms", 0.0)),
                "Bandwidth (Mbps)": float(t.get("net_bw_mbps", 0.0)),
                "Price Per Hour": float(t.get("price_per_hour_usd", 0.0)),
                "Reliability": float(t.get("reliability", 0.0)),
                "Power (W)": float(t.get("power_w", 0.0)),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty and "Time" in df.columns:
        df["Time"] = pd.to_datetime(df["Time"], errors="coerce")
    return df


def telemetry_history(df_now: pd.DataFrame, keep: int = 25) -> pd.DataFrame:
    snap = datetime.utcnow().strftime("%H:%M:%S")
    df = df_now.copy()
    df["Snapshot"] = snap

    hist = st.session_state.get("telemetry_hist", [])
    hist.append(df)
    hist = hist[-keep:]
    st.session_state["telemetry_hist"] = hist
    return pd.concat(hist, ignore_index=True)


def job_outcomes_df(jobs: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(jobs)
    if df.empty:
        return df

    if "status" not in df.columns:
        return pd.DataFrame()

    df = df[df["status"] == "COMPLETED"].copy()
    if df.empty:
        return df

    for col in ["updated_at", "created_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # keep only jobs with actuals
    if "actual_latency_ms" in df.columns and "actual_cost_usd" in df.columns:
        df = df[df["actual_latency_ms"].notna() & df["actual_cost_usd"].notna()]

    df = df.sort_values("updated_at" if "updated_at" in df.columns else df.columns[0])
    df["Step"] = range(1, len(df) + 1)
    return df


def timeline_figure(events_payload):
    """Robust timeline: works for list OR dict wrapper."""
    ev = normalize_list(events_payload)
    if not ev:
        fig = go.Figure()
        fig.update_layout(
            height=160,
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            annotations=[
                dict(
                    text="No events yet",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=14),
                )
            ],
        )
        return fig

    df = pd.DataFrame(ev)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
        df = df.sort_values("ts")
    else:
        df["ts"] = pd.NaT

    df["idx"] = range(1, len(df) + 1)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["ts"],
            y=df["idx"],
            mode="lines+markers+text",
            text=df["event"] if "event" in df.columns else df["idx"].astype(str),
            textposition="top center",
            hovertext=df["message"] if "message" in df.columns else None,
            hoverinfo="text",
        )
    )

    fig.update_layout(
        height=260,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Time",
        yaxis=dict(title="", showticklabels=False, zeroline=False),
    )
    return fig


def job_form(prefix: str):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        job_type = st.selectbox(
            f"{prefix} Job Type",
            ["inference", "batch", "training"],
            index=0,
            key=f"{prefix}-job-type",
        )
    with c2:
        urgency = st.slider(
            f"{prefix} Urgency",
            0.0,
            1.0,
            0.7,
            0.05,
            key=f"{prefix}-urgency",
        )
    with c3:
        payload = st.number_input(
            f"{prefix} Payload (MB)",
            min_value=0.0,
            value=50.0,
            step=5.0,
            key=f"{prefix}-payload",
        )
    with c4:
        requires_gpu = st.checkbox(
            f"{prefix} Requires GPU",
            value=False,
            key=f"{prefix}-gpu",
        )

    d1, d2, d3, d4 = st.columns(4)
    with d1:
        deadline_ms = st.number_input(
            f"{prefix} SLA Deadline (ms)",
            min_value=0,
            value=2500,
            step=100,
            key=f"{prefix}-deadline",
        )
    with d2:
        max_cost = st.number_input(
            f"{prefix} SLA Max Cost (USD)",
            min_value=0.0,
            value=0.06,
            step=0.01,
            format="%.3f",
            key=f"{prefix}-maxcost",
        )
    with d3:
        min_rel = st.slider(
            f"{prefix} SLA Min Reliability",
            0.80,
            0.999,
            0.95,
            0.005,
            key=f"{prefix}-minrel",
        )
    with d4:
        allow_sla_fallback = st.checkbox(
            f"{prefix} Allow SLA Fallback",
            value=True,
            key=f"{prefix}-fallback",
        )

    # Optional demo hints
    with st.expander("Demo Controls (optional)", expanded=False):
        h1, h2, h3, h4 = st.columns(4)
        with h1:
            force_fail_first = st.checkbox(
                "Force First Attempt Failure",
                value=False,
                key=f"{prefix}-force-fail",
            )
        with h2:
            force_type = st.selectbox(
                "Force Resource Type",
                ["(none)", "edge", "cloud", "gpu"],
                index=0,
                key=f"{prefix}-force-type",
            )
        with h3:
            force_id = st.text_input(
                "Force Resource Id",
                value="",
                key=f"{prefix}-force-id",
                placeholder="Example: edge-2",
            )
        with h4:
            exclude_ids = st.text_input(
                "Exclude Resource Ids",
                value="",
                key=f"{prefix}-exclude",
                placeholder="Comma list: edge-1,cloud-2",
            )

        hints = {}
        if force_fail_first:
            hints["force_fail_first"] = True
        if force_type != "(none)":
            hints["force_resource_type"] = force_type
        if force_id.strip():
            hints["force_resource_id"] = force_id.strip()
        if exclude_ids.strip():
            hints["exclude_resource_ids"] = [x.strip() for x in exclude_ids.split(",") if x.strip()]
    job_id = f"ui-{int(time.time())}"

    payload_json = {
        "job_id": job_id,
        "job_type": job_type,
        "urgency": urgency,
        "payload_size_mb": float(payload),
        "requires_gpu": bool(requires_gpu),
        "allow_sla_fallback": bool(allow_sla_fallback),
        "sla": {
            "deadline_ms": int(deadline_ms) if deadline_ms > 0 else None,
            "max_cost_usd": float(max_cost) if max_cost > 0 else None,
            "min_reliability": float(min_rel),
        },
        "hints": hints,
    }
    return payload_json


def considered_table(decision: dict):
    considered = decision.get("considered", []) if isinstance(decision, dict) else []
    if not considered:
        st.info("No considered resources returned.")
        return

    flat = []
    for item in considered:
        s = item.get("score", {})
        flat.append(
            {
                "Resource": item.get("resource_id"),
                "Type": (item.get("resource_type") or "").title(),
                "Final Score": s.get("final_score"),
                "Effective Score": s.get("effective_score", s.get("final_score")),
                "SLA OK": bool(s.get("sla_ok", True)),
                "Predicted Latency (ms)": s.get("latency_pred_ms"),
                "Predicted Cost (USD)": s.get("cost_pred_usd"),
                "Reliability": s.get("reliability"),
                "Congestion": s.get("congestion"),
                "SLA Notes": " | ".join(s.get("sla_violations", [])) if s.get("sla_violations") else "",
            }
        )

    df = pd.DataFrame(flat)
    df = df.sort_values(["SLA OK", "Effective Score"], ascending=[False, False])

    st.dataframe(
        df,
        use_container_width=True,
        height=280,
        hide_index=True,
        column_config={
            "Final Score": st.column_config.NumberColumn(format="%.3f"),
            "Effective Score": st.column_config.NumberColumn(format="%.3f"),
            "Predicted Latency (ms)": st.column_config.NumberColumn(format="%.0f"),
            "Predicted Cost (USD)": st.column_config.NumberColumn(format="$%.4f"),
            "Reliability": st.column_config.NumberColumn(format="%.3f"),
            "Congestion": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    fig = px.bar(
        df,
        x="Resource",
        y="Effective Score",
        color="Type",
        title="Effective Score by Resource",
    )
    st.plotly_chart(fig, use_container_width=True)


# ---------------- Header ----------------
st.title("PBS Final v3 Dashboard")
st.caption(f"Backend: {BACKEND}")

# ---------------- Sidebar ----------------
with st.sidebar:
    st.subheader("Controls")
    refresh = st.slider("Auto Refresh (seconds)", 0, 10, 2, help="0 disables auto refresh")
    show_advanced = st.toggle("Show Advanced Columns", value=False)
    telemetry_frames = st.slider("Telemetry Animation History", 5, 40, 20, 5)

    st.divider()
    st.subheader("Quick Checks")
    if st.button("Ping Backend"):
        try:
            st.success(safe_get("/health", timeout=2))
        except Exception as e:
            st.error(str(e))

    st.markdown(f"[Open API Docs]({BACKEND}/docs)")

    st.divider()
    st.subheader("Worker Command")
    st.code(
        "cd backend\n"
        "$env:PYTHONPATH = (Get-Location).Path\n"
        "..\\.\\.venv\\Scripts\\python.exe worker.py",
        language="powershell",
    )
    st.caption("Run worker in a separate terminal to execute queued jobs.")

# ---------------- Tabs ----------------
tabs = st.tabs(
    [
        "Overview",
        "Live Resources",
        "Route Explorer",
        "Submit Jobs",
        "Job Monitor",
        "SLA and Events",
        "Model and Learning",
    ]
)

# ---------------- Overview ----------------
with tabs[0]:
    st.markdown('<div class="section-box">', unsafe_allow_html=True)
    st.markdown('<div class="section-title"><span class="pulse"></span>System Status</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Use this first in front of judges: “everything is live.”</div>', unsafe_allow_html=True)

    left, right = st.columns([1, 1])
    with left:
        try:
            health = safe_get("/health", timeout=2)
            st.success(health)
        except Exception as e:
            st.error(f"Backend not reachable: {e}")

    with right:
        try:
            mm = safe_get("/jobs/model-metrics", timeout=3)
            st.markdown(
                f"""
                <div class="kpi-row">
                  <div class="kpi"><div class="kpi-label">Completed Jobs</div><div class="kpi-value">{mm.get("completed_jobs", 0)}</div></div>
                  <div class="kpi"><div class="kpi-label">Latency MAE</div><div class="kpi-value">{mm.get("latency_mae_ms", 0):.1f} ms</div></div>
                  <div class="kpi"><div class="kpi-label">Cost MAE</div><div class="kpi-value">{mm.get("cost_mae_usd", 0):.6f}</div></div>
                  <div class="kpi"><div class="kpi-label">Learning Loop</div><div class="kpi-value">On</div></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        except Exception:
            st.info("Model metrics not available yet.")

    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown('<div class="section-box">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Demo Flow</div>', unsafe_allow_html=True)
    st.markdown(
        """
<div class="section-sub">
Recommended judge flow (fast and convincing):
</div>
<div class="badge">1. Live Resources updating</div>
<div class="badge">2. Route Explorer explanation</div>
<div class="badge">3. Submit Jobs and watch lifecycle</div>
<div class="badge">4. Show reroute on failure</div>
<div class="badge">5. Show model metrics improving</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Live Resources ----------------
with tabs[1]:
    st.markdown('<div class="section-box">', unsafe_allow_html=True)
    st.markdown('<div class="section-title"><span class="pulse"></span>Live Resources (Latest Telemetry)</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Clean table + animated curves using recent telemetry snapshots.</div>', unsafe_allow_html=True)

    try:
        resources = safe_get("/resources", timeout=5)
    except Exception as e:
        st.error(f"Failed to load resources: {e}")
        st.stop()

    df = clean_resources_df(resources)
    if df.empty:
        st.warning("No telemetry yet. Run telemetry simulator script from backend.")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        avg_rtt = df["RTT (ms)"].mean()
        avg_rel = df["Reliability"].mean()
        total = len(df)
        gpu_count = int((df["Type"] == "Gpu").sum())
        cloud_count = int((df["Type"] == "Cloud").sum())
        edge_count = int((df["Type"] == "Edge").sum())

        st.markdown(
            f"""
            <div class="kpi-row">
              <div class="kpi"><div class="kpi-label">Resources</div><div class="kpi-value">{total}</div></div>
              <div class="kpi"><div class="kpi-label">Edge / Cloud / GPU</div><div class="kpi-value">{edge_count} / {cloud_count} / {gpu_count}</div></div>
              <div class="kpi"><div class="kpi-label">Average RTT</div><div class="kpi-value">{avg_rtt:.1f} ms</div></div>
              <div class="kpi"><div class="kpi-label">Average Reliability</div><div class="kpi-value">{avg_rel:.3f}</div></div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Clean table
        base_cols = ["Resource", "Type", "Time", "RTT (ms)", "Price Per Hour", "Reliability", "CPU", "Memory", "GPU"]
        adv_cols = ["Bandwidth (Mbps)", "Power (W)"]
        cols = base_cols + (adv_cols if show_advanced else [])

        df_show = df[cols].copy().sort_values(["Type", "Resource"])

        st.dataframe(
            df_show,
            use_container_width=True,
            height=360,
            hide_index=True,
            column_config={
                "CPU": st.column_config.NumberColumn(format="%.2f"),
                "Memory": st.column_config.NumberColumn(format="%.2f"),
                "GPU": st.column_config.NumberColumn(format="%.2f"),
                "RTT (ms)": st.column_config.NumberColumn(format="%.1f"),
                "Bandwidth (Mbps)": st.column_config.NumberColumn(format="%.1f"),
                "Price Per Hour": st.column_config.NumberColumn(format="$%.4f"),
                "Reliability": st.column_config.NumberColumn(format="%.3f"),
                "Power (W)": st.column_config.NumberColumn(format="%.0f"),
            },
        )

        st.markdown("</div>", unsafe_allow_html=True)

        # Animated telemetry curve
        st.markdown('<div class="section-box">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Latency and Cost Curve (Animated)</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">This animates using recent telemetry snapshots. Turn on auto refresh for live motion.</div>', unsafe_allow_html=True)

        hist = telemetry_history(
            df[["Resource", "Type", "RTT (ms)", "Price Per Hour", "Power (W)"]],
            keep=telemetry_frames,
        )
        hist = hist.sort_values(["Snapshot", "Type", "RTT (ms)"])

        fig = px.line(
            hist,
            x="RTT (ms)",
            y="Price Per Hour",
            color="Type",
            line_shape="spline",
            animation_frame="Snapshot",
            markers=True,
            hover_name="Resource",
        )
        fig.update_layout(
            margin=dict(l=10, r=10, t=10, b=10),
            legend_title_text="Type",
        )
        fig.layout.updatemenus = [
            {
                "type": "buttons",
                "showactive": False,
                "x": 1.02,
                "y": 1.15,
                "buttons": [
                    {
                        "label": "Play",
                        "method": "animate",
                        "args": [
                            None,
                            {
                                "frame": {"duration": 350, "redraw": True},
                                "transition": {"duration": 220},
                                "fromcurrent": True,
                            },
                        ],
                    },
                    {
                        "label": "Pause",
                        "method": "animate",
                        "args": [
                            [None],
                            {
                                "mode": "immediate",
                                "frame": {"duration": 0, "redraw": False},
                                "transition": {"duration": 0},
                            },
                        ],
                    },
                ],
            }
        ]
        st.plotly_chart(fig, use_container_width=True)
        st.markdown("</div>", unsafe_allow_html=True)

        # Job outcomes curve
        st.markdown('<div class="section-box">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Job Outcomes Curve (Grows as Tasks Complete)</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-sub">This is the “proof” panel: as jobs finish, this curve grows automatically.</div>', unsafe_allow_html=True)

        try:
            jobs = safe_get("/jobs", timeout=5)
        except Exception:
            jobs = []

        jdf = job_outcomes_df(jobs)
        if jdf.empty:
            st.info("No completed jobs yet. Submit a job and let the worker execute it.")
        else:
            fig2 = px.line(
                jdf,
                x="actual_latency_ms",
                y="actual_cost_usd",
                markers=True,
                line_shape="spline",
                hover_name="job_id",
            )
            fig2.update_layout(
                xaxis_title="Actual Latency (ms)",
                yaxis_title="Actual Cost (USD)",
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Route Explorer ----------------
with tabs[2]:
    st.markdown('<div class="section-box">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Route Explorer</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Explains how the router chooses Edge, Cloud, or GPU under SLA constraints.</div>', unsafe_allow_html=True)

    payload = job_form("Route")

    if st.button("Compute Route Decision"):
        try:
            dec = safe_post("/route", payload)
            if dec.get("chosen_resource_id") == "none":
                st.error(dec.get("explanation", "No route found"))
            else:
                st.success(dec.get("explanation", "Route computed"))
            considered_table(dec)
        except Exception as e:
            st.error(f"Route failed: {e}")

    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Submit Jobs ----------------
with tabs[3]:
    st.markdown('<div class="section-box">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Submit Jobs (Queue for Worker)</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Submits to the backend. Worker picks it up and executes. Use “force first attempt failure” to demo reroute.</div>', unsafe_allow_html=True)

    payload = job_form("Submit")
    if st.button("Submit Job"):
        try:
            out = safe_post("/jobs", payload)
            st.success(f"Submitted. Status: {out.get('status')}")
            dec = out.get("decision", {})
            if dec:
                st.write(dec.get("explanation", ""))
                considered_table(dec)

            st.info("Open Job Monitor tab to watch events and attempts.")
        except Exception as e:
            st.error(f"Submit failed: {e}")

    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Job Monitor ----------------
with tabs[4]:
    st.markdown('<div class="section-box">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Job Monitor</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Pick a job and show lifecycle: submitted → running → rerouted/retry → completed.</div>', unsafe_allow_html=True)

    try:
        jobs = safe_get("/jobs", timeout=5)
    except Exception as e:
        st.error(f"Failed to load jobs: {e}")
        jobs = []

    if not jobs:
        st.info("No jobs yet. Submit one from Submit Jobs tab.")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        dfj = pd.DataFrame(jobs)

        cols = [
            c
            for c in [
                "job_id",
                "status",
                "chosen_resource_type",
                "chosen_resource_id",
                "attempts",
                "predicted_latency_ms",
                "predicted_cost_usd",
                "actual_latency_ms",
                "actual_cost_usd",
                "updated_at",
            ]
            if c in dfj.columns
        ]
        st.dataframe(dfj[cols], use_container_width=True, height=280, hide_index=True)

        job_ids = dfj["job_id"].tolist()
        sel = st.selectbox("Select Job", job_ids, index=0)

        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            if st.button("Refresh Selected Job"):
                st.rerun()
        with c2:
            if st.button("Cancel Selected Job"):
                try:
                    safe_post(f"/jobs/{sel}/cancel", {})
                    st.warning("Cancel requested.")
                except Exception as e:
                    st.error(str(e))
        with c3:
            st.caption("If job is stuck queued, worker is not running.")

        try:
            details = safe_get(f"/jobs/{sel}", timeout=5)
        except Exception as e:
            st.error(f"Failed to load job details: {e}")
            details = {}

        try:
            events_payload = safe_get(f"/jobs/{sel}/events", timeout=5)
        except Exception:
            events_payload = []

        try:
            attempts_payload = safe_get(f"/jobs/{sel}/attempts", timeout=5)
        except Exception:
            attempts_payload = []

        # Summary KPIs
        if details:
            pred_lat = details.get("predicted_latency_ms")
            act_lat = details.get("actual_latency_ms")
            pred_cost = details.get("predicted_cost_usd")
            act_cost = details.get("actual_cost_usd")

            st.markdown(
                f"""
                <div class="kpi-row">
                  <div class="kpi"><div class="kpi-label">Status</div><div class="kpi-value">{details.get("status","")}</div></div>
                  <div class="kpi"><div class="kpi-label">Chosen</div><div class="kpi-value">{details.get("chosen_resource_type","")} {details.get("chosen_resource_id","")}</div></div>
                  <div class="kpi"><div class="kpi-label">Latency Pred / Actual</div><div class="kpi-value">{(pred_lat or 0):.0f} / {(act_lat or 0):.0f}</div></div>
                  <div class="kpi"><div class="kpi-label">Cost Pred / Actual</div><div class="kpi-value">{(pred_cost or 0):.4f} / {(act_cost or 0):.4f}</div></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown('<div class="section-title">Execution Timeline</div>', unsafe_allow_html=True)
        st.plotly_chart(timeline_figure(events_payload), use_container_width=True)

        st.markdown('<div class="section-title">Events</div>', unsafe_allow_html=True)
        ev_list = normalize_list(events_payload)
        if ev_list:
            st.dataframe(pd.DataFrame(ev_list), use_container_width=True, height=220, hide_index=True)
        else:
            st.info("No events yet.")

        st.markdown('<div class="section-title">Attempts</div>', unsafe_allow_html=True)
        at_list = normalize_list(attempts_payload)
        if at_list:
            dfa = pd.DataFrame(at_list)
            st.dataframe(dfa, use_container_width=True, height=240, hide_index=True)

            # Pred vs Actual chart for attempts that completed
            if "status" in dfa.columns and "predicted_latency_ms" in dfa.columns and "actual_latency_ms" in dfa.columns:
                done = dfa[dfa["status"] == "COMPLETED"].copy()
                if not done.empty:
                    fig_pa = go.Figure()
                    fig_pa.add_trace(go.Scatter(
                        x=done["attempt_no"], y=done["predicted_latency_ms"],
                        mode="lines+markers", name="Predicted Latency"
                    ))
                    fig_pa.add_trace(go.Scatter(
                        x=done["attempt_no"], y=done["actual_latency_ms"],
                        mode="lines+markers", name="Actual Latency"
                    ))
                    fig_pa.update_layout(
                        height=280,
                        margin=dict(l=10, r=10, t=10, b=10),
                        xaxis_title="Attempt Number",
                        yaxis_title="Latency (ms)",
                    )
                    st.plotly_chart(fig_pa, use_container_width=True)
        else:
            st.info("No attempts yet.")

        st.markdown("</div>", unsafe_allow_html=True)

# ---------------- SLA and Events ----------------
with tabs[5]:
    st.markdown('<div class="section-box">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">SLA and System Events</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Show blocked jobs and SLA violations here. This proves SLA control is real.</div>', unsafe_allow_html=True)

    try:
        sla_events = safe_get("/jobs/sla-events", timeout=5)
    except Exception as e:
        st.error(f"Failed to load SLA events: {e}")
        sla_events = []

    if not sla_events:
        st.info("No SLA events so far.")
    else:
        df = pd.DataFrame(sla_events)
        st.dataframe(df, use_container_width=True, height=320, hide_index=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Model and Learning ----------------
with tabs[6]:
    st.markdown('<div class="section-box">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Model and Learning Loop</div>', unsafe_allow_html=True)
    st.markdown(
        """
<div class="section-sub">
This is your “self improving” layer:
the system stores predicted values and real outcomes, then uses the gap to train better predictors.
</div>
<div class="badge">Features captured</div>
<div class="badge">Prediction made</div>
<div class="badge">Actual measured</div>
<div class="badge">Error computed</div>
<div class="badge">Model updated</div>
""",
        unsafe_allow_html=True,
    )

    try:
        mm = safe_get("/jobs/model-metrics", timeout=5)
        st.json(mm)
    except Exception as e:
        st.error(f"Failed to load model metrics: {e}")

    st.markdown(
        """
<div class="small-note">
What judges should understand:
Predicted latency and cost are checked against actual values.
That error becomes training data (supervised learning) so routing becomes smarter over time.
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)

# ---------------- Auto refresh ----------------
if refresh > 0:
    time.sleep(refresh)
    st.rerun()
