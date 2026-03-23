# prompts.py

# ---------------------------------------------------------------------------
# REAL EXAMPLE REPORTS — embedded so the LLM matches style exactly
# ---------------------------------------------------------------------------

EXAMPLE_REPORTS = """
=== Q1 2024 ===
The strong market momentum from 2023 spilled over into the first quarter of this year, as global equity markets marched higher on much better-than-feared economic data, an improving corporate earnings picture, and a continuation of the AI mania that dominated last year's market narrative. The MSCI All-Country World Index (ACWI) of global stocks gained 8.2% for the quarter to finish at a new high-water mark, representing its 21st new record high so far this year.
The S&P 500 Index logged a 10.6% total return during the first quarter, capping a five-month win streak during which blue chip U.S. stocks advanced 30% off of late October lows and added more than $9 trillion in market value. The index reached a new record high on January 24th, fully erasing the bear market losses from 2022, and the S&P notched 21 more records before quarter end.

=== Q2 2024 ===
Fueled by a moderating of global inflationary pressure, growing optimism around an easing of financial conditions by central bankers that seems increasingly imminent, and a continuation of the AI-mania that has gripped investors for more than a year, global equity markets continued their hot streak through the second quarter. The MSCI All-Country World Index (ACWI) of global stocks gained 2.9% in Q2, capping an 11.3% total return for the global blue-chip benchmark through mid-year and a near 50% rally since stocks bottomed in late September of 2022.
The S&P 500 Index logged a 4.3% total return during the second quarter, boosting year-to-date gains to 15.3% and continuing a three-quarter win streak that has added more than $10 trillion in market value. Through Q2, the S&P notched 31 new records highs so far this year.

=== Q3 2024 ===
Global equity markets enjoyed a strong, broad-based rally during the third quarter, as stronger corporate earnings, better-than-expected economic data, and the official launch of the Federal Reserve's long-awaited rate cutting cycle fueled demand for risk assets. The MSCI All-Country World Index (ACWI) of global stocks gained 6.6% in Q3, bringing year-to-date returns to 18.7%.
The S&P 500 Index logged a 5.9% total return during the third quarter to boost YTD gains to 22.1%, continuing a four-quarter win streak and capping the best YTD September return for the blue-chip index since 1997. The S&P closed the quarter at a new all-time high, its 43rd record close so far this year.

=== Q4 2024 ===
Despite a late December sell off, global equity markets gave investors a lot to cheer in 2024, posting a second consecutive year of strong, double-digit returns. The MSCI All-Country World Index (ACWI) of global stocks retreated 1.0% in Q4, but the index still posted a full-year total return of 17.5% to extend the current bull market past the two-year mark.
The S&P 500 Index logged a 2.4% total return during the fourth quarter to boost full-year gains to 25.0%, continuing a five-quarter win streak and capping the best two-year return (57.9%) for the blue-chip index since 1997-98. The S&P hit 57 new record highs and added $10 trillion in market value in 2024.
"""

# ---------------------------------------------------------------------------
# SUPERVISOR PROMPT
# ---------------------------------------------------------------------------

supervisor_prompt_template = """You are the workflow supervisor for a quarterly equity market report system.

Current state:
- Market data collected: {has_market_data}
- News/narrative context: {has_news}
- Draft exists: {has_draft}
- Critique notes: {critique}
- Revision number: {revision_number}

Decide the next step. Respond with ONLY a JSON object:

{{
  "next_step": "data_collector" | "news_researcher" | "writer" | "END",
  "reason": "one sentence explanation"
}}

Rules:
- If market data is missing → "data_collector"
- If market data exists but news context is missing → "news_researcher"
- If news exists but no draft → "writer"
- If critique says APPROVED → "END"
- If critique has feedback and revision_number < 2 → "writer"
- If revision_number >= 2 → "END"
"""

# ---------------------------------------------------------------------------
# NEWS RESEARCHER PROMPT (passed as search queries context)
# ---------------------------------------------------------------------------

news_researcher_prompt_template = """You are a financial news analyst.
Summarize the key market themes and drivers for {quarter} {year} based on these search results:

{search_results}

Focus on:
1. Main macro drivers (inflation, interest rates, economic growth)
2. Federal Reserve actions / central bank decisions
3. Key market themes (AI, tech, earnings, geopolitical events)
4. Any significant market events (rallies, sell-offs, volatility)
5. Corporate earnings trends

Be concise — 5 to 8 bullet points. This will be used by a financial writer.
"""

# ---------------------------------------------------------------------------
# WRITER PROMPT
# ---------------------------------------------------------------------------

writer_prompt_template = """You are a professional financial writer for an investment management firm.
Your task is to write a quarterly equity market report that EXACTLY matches the style, tone, length, and structure of these real examples:

{example_reports}

---
MARKET DATA FOR {quarter} {year}:
{market_data}

KEY MARKET THEMES / NARRATIVE:
{news_context}

REVISION NOTES (if any):
{critique}
---

Write the {quarter} {year} quarterly equity market report now.

STRICT FORMAT RULES:
- Exactly TWO paragraphs — no headers, no bullet points, no titles
- Paragraph 1: Global equity markets — open with a tone-setting phrase, list 2-3 key drivers, state the MSCI ACWI quarterly return %, add YTD or record high context
- Paragraph 2: S&P 500 — state quarterly total return %, YTD gains, mention the win streak (N-quarter win streak), mention record highs count
- Use ONLY the numbers from the market data above — do not invent or estimate figures
- Match the professional, confident writing style of the examples precisely
- Target length: ~150-200 words total

Output ONLY the two paragraphs. Nothing else.
"""

# ---------------------------------------------------------------------------
# CRITIQUE PROMPT
# ---------------------------------------------------------------------------

critique_prompt_template = """You are a senior editor reviewing a quarterly equity market report draft.

MARKET DATA (ground truth):
{market_data}

DRAFT TO REVIEW:
{draft}

STYLE REFERENCE (what good looks like):
{example_reports}

Evaluate the draft on these criteria:
1. FORMAT — Exactly two paragraphs? No headers or bullet points?
2. ACCURACY — Are the ACWI and S&P 500 return percentages correct per the market data?
3. COMPLETENESS — Does it mention ACWI return, S&P 500 return, YTD return, win streak, and record highs?
4. STYLE — Does it match the professional, flowing tone of the style reference?
5. LENGTH — Approximately 150-200 words?

If ALL criteria are met, respond with exactly: APPROVED
Otherwise, provide specific, numbered feedback for the writer to fix. Be concise.
"""
