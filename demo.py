# app.py

import os
import json
import time
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

API_URL = os.environ.get("API_URL", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Equity Market Report Generator",
    page_icon="📈",
    layout="wide",
)

# ---------------------------------------------------------------------------
# API key check
# ---------------------------------------------------------------------------

def check_api_keys():
    missing = [k for k in ("NVIDIA_API_KEY", "TAVILY_API_KEY")
               if not os.environ.get(k)]
    if missing:
        st.error(f"Missing API keys in .env: {', '.join(missing)}")
        return False
    return True

# ---------------------------------------------------------------------------
# SSE consumer
# ---------------------------------------------------------------------------

def consume_sse(prompt: str, quarter: str | None, year: int | None, max_iter: int):
    """
    POST to /generate and yield (event_type, data) tuples as they arrive.
    """
    payload = {
        "prompt": prompt,
        "quarter": quarter,
        "year": year,
        "max_iterations": max_iter,
    }
    with requests.post(
        f"{API_URL}/generate",
        json=payload,
        stream=True,
        timeout=300,
    ) as resp:
        resp.raise_for_status()
        event_type = "message"
        for raw in resp.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
                yield event_type, data
                event_type = "message"

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("📈 Quarterly Equity Market Report Generator")
st.markdown(
    "Powered by **NVIDIA AI** · **yfinance** · **Tavily** · **LangGraph**\n\n"
    "Enter a quarter and year to automatically generate a professional equity market report."
)
st.divider()

if not check_api_keys():
    st.stop()

# ---------------------------------------------------------------------------
# Input section
# ---------------------------------------------------------------------------

col_input, col_selectors = st.columns([3, 2])

with col_input:
    user_prompt = st.text_input(
        "Natural language prompt",
        placeholder='e.g.  "Generate the Equity market report for Q1 2025"',
        key="prompt_input",
    )

with col_selectors:
    st.caption("Or pick directly:")
    c1, c2 = st.columns(2)
    with c1:
        quarter_sel = st.selectbox("Quarter", ["Q1", "Q2", "Q3", "Q4"], index=0)
    with c2:
        year_sel = st.number_input("Year", min_value=2000, max_value=2030,
                                   value=2025, step=1)

# Selectbox values are fallback — used only if prompt has no quarter/year
st.caption(f"Fallback selection: **{quarter_sel} {int(year_sel)}**")

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("⚙️ Configuration")
    max_iter = st.slider("Max workflow iterations", 5, 20, 12)
    st.divider()
    st.subheader("📋 Agent pipeline")
    st.markdown("""
    1. **Supervisor** — routes the workflow
    2. **Data Collector** — fetches ACWI & S&P 500 metrics via yfinance
    3. **News Researcher** — finds market themes via Tavily
    4. **Writer** — drafts the 2-paragraph report
    5. **Critiquer** — checks accuracy & style; loops if needed
    """)
    st.divider()
    st.subheader("📊 Report metrics")
    st.markdown("""
    - MSCI ACWI quarterly & YTD return
    - S&P 500 quarterly & YTD return
    - Record highs count
    - Win streak (consecutive positive quarters)
    - Fed Funds Rate *(if FRED_API_KEY set)*
    """)
    st.divider()
    st.caption(f"API: `{API_URL}`")

# ---------------------------------------------------------------------------
# Generate button
# ---------------------------------------------------------------------------

if st.button("🚀 Generate Report", type="primary", use_container_width=True):

    progress_bar = st.progress(0)
    status_box   = st.empty()
    activity_box = st.container()

    final_draft       = ""
    final_market_data = {}
    final_quarter     = quarter_sel
    final_year        = int(year_sel)
    step_count        = 0

    status_box.info("⏳ Starting pipeline…")

    try:
        for event_type, data in consume_sse(
            prompt    = user_prompt or "",
            quarter   = quarter_sel,
            year      = int(year_sel),
            max_iter  = max_iter,
        ):
            # ── resolved ────────────────────────────────────────────────────
            if event_type == "resolved":
                final_quarter = data["quarter"]
                final_year    = data["year"]
                status_box.info(f"Generating **{final_quarter} {final_year}** equity market report…")

            # ── step (agent activity) ────────────────────────────────────────
            elif event_type == "step":
                step_count += 1
                progress_bar.progress(min(step_count / max_iter, 0.9))

                node_name   = data.get("node", "")
                node_output = data.get("data", {})

                with activity_box:

                    if node_name == "supervisor":
                        # Non-report input — supervisor replies directly and ends
                        if node_output.get("chat_reply"):
                            progress_bar.empty()
                            status_box.empty()
                            st.chat_message("assistant").markdown(node_output["chat_reply"])
                            st.stop()
                        decision = node_output.get("next_step", "")
                        st.markdown(f"**🎯 Supervisor** → routing to `{decision}`")

                    elif node_name == "data_collector":
                        md = node_output.get("market_data", {})
                        st.success("✅ Market data collected")
                        with st.expander("📊 View raw market data"):
                            ca, cb = st.columns(2)
                            with ca:
                                st.metric("ACWI Quarterly", f"{md.get('acwi_return', 'N/A')}%")
                                st.metric("ACWI YTD",       f"{md.get('acwi_ytd', 'N/A')}%")
                            with cb:
                                st.metric("S&P 500 Quarterly", f"{md.get('sp500_return', 'N/A')}%")
                                st.metric("S&P 500 YTD",       f"{md.get('sp500_ytd', 'N/A')}%")
                            st.metric("Record Highs YTD", md.get('sp500_record_highs_ytd', 'N/A'))
                            st.metric("Win Streak", f"{md.get('sp500_win_streak', 'N/A')} quarters")

                    elif node_name == "news_researcher":
                        st.success("✅ Market narrative gathered")
                        with st.expander("📰 View news context"):
                            st.markdown(node_output.get("news_context", ""))

                    elif node_name == "writer":
                        draft = node_output.get("draft", "")
                        rev   = node_output.get("revision_number", 0)
                        st.success(f"✅ Draft {rev} written ({len(draft)} chars)")
                        with st.expander(f"📝 View draft {rev}"):
                            st.markdown(draft)

                    elif node_name == "critiquer":
                        critique = node_output.get("critique", "")
                        if "APPROVED" in critique.upper():
                            st.success("✅ Draft APPROVED by critiquer")
                        else:
                            st.warning("📝 Critiquer requested revisions")
                        with st.expander("🔍 View critique"):
                            st.markdown(critique)

                    st.divider()

            # ── complete ─────────────────────────────────────────────────────
            elif event_type == "complete":
                final_draft       = data.get("report", "")
                final_market_data = data.get("market_data", {})
                final_quarter     = data.get("quarter", final_quarter)
                final_year        = data.get("year", final_year)

            # ── error ────────────────────────────────────────────────────────
            elif event_type == "error":
                status_box.error(f"❌ {data.get('message', 'Unknown error')}")
                st.stop()

    except requests.exceptions.ConnectionError:
        st.error(f"Cannot reach API at `{API_URL}`. Is the server running?\n\n"
                 "`uvicorn src.api:api --port 8000`")
        st.stop()
    except requests.exceptions.HTTPError as e:
        st.error(f"❌ API returned {e.response.status_code}")
        st.code(e.response.text, language="text")
        st.stop()
    except Exception as e:
        status_box.error("❌ Error during generation")
        st.exception(e)
        st.stop()

    progress_bar.progress(1.0)
    status_box.success("✅ Report complete!")

    # ------------------------------------------------------------------------
    # Final report
    # ------------------------------------------------------------------------

    st.divider()

    if final_draft:
        st.header(f"📄 {final_quarter} {final_year} Equity Market Report")

        st.markdown(
            f"""
            <div style="
                background:#f8f9fa;
                border-left: 4px solid #1f6feb;
                padding: 1.5rem 2rem;
                border-radius: 6px;
                font-size: 1.05rem;
                line-height: 1.75;
                color: #1a1a2e;
            ">
            {final_draft.replace(chr(10), '<br><br>')}
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.divider()

        if final_market_data:
            st.subheader("📊 Key Metrics Used")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("ACWI Return",    f"{final_market_data.get('acwi_return', 'N/A')}%")
            c2.metric("S&P 500 Return", f"{final_market_data.get('sp500_return', 'N/A')}%")
            c3.metric("S&P 500 YTD",    f"{final_market_data.get('sp500_ytd', 'N/A')}%")
            c4.metric("Record Highs",   final_market_data.get('sp500_record_highs_ytd', 'N/A'))

        st.download_button(
            label="📥 Download Report (.txt)",
            data=final_draft,
            file_name=f"equity_report_{final_quarter}_{final_year}.txt",
            mime="text/plain",
            use_container_width=True,
        )
    else:
        st.error("No report was generated. Check the agent logs above for errors.")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.markdown(
    "<div style='text-align:center;color:gray;'>Powered by NVIDIA AI · LangGraph · yfinance · Tavily</div>",
    unsafe_allow_html=True,
)
