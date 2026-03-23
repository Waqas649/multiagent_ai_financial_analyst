# data_collector.py
"""
Fetches all financial metrics needed for the quarterly equity market report.
Data sources: yfinance (ACWI ETF, ^GSPC) and optionally FRED (Fed Funds Rate).
"""

import os
import calendar
import pandas as pd
import yfinance as yf

try:
    from fredapi import Fred
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False


def _sanitize(obj):
    """Recursively convert numpy scalars → native Python types so msgpack can serialize them."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


QUARTER_MONTHS = {
    'Q1': (1, 3),
    'Q2': (4, 6),
    'Q3': (7, 9),
    'Q4': (10, 12),
}

QUARTER_NAMES = {
    'Q1': 'first',
    'Q2': 'second',
    'Q3': 'third',
    'Q4': 'fourth',
}


def get_quarter_dates(quarter: str, year: int):
    """Return (start_date_str, end_date_str) for a given quarter."""
    m_start, m_end = QUARTER_MONTHS[quarter.upper()]
    last_day = calendar.monthrange(year, m_end)[1]
    return f"{year}-{m_start:02d}-01", f"{year}-{m_end:02d}-{last_day}"


def fetch_prices(ticker: str, start: str, end: str) -> pd.Series:
    """Download adjusted close prices. Returns empty Series on failure."""
    try:
        data = yf.download(ticker, start=start, end=end,
                           auto_adjust=True, progress=False)
        if data.empty:
            return pd.Series(dtype=float)
        # Flatten MultiIndex columns that yfinance sometimes returns
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = [col[0] for col in data.columns]
        return data['Close'].dropna()
    except Exception as e:
        print(f"[data_collector] fetch_prices({ticker}) error: {e}")
        return pd.Series(dtype=float)


def pct_return(prices: pd.Series) -> float:
    """Percentage return from first to last observation."""
    if len(prices) < 2:
        return 0.0
    return float(round(((prices.iloc[-1] / prices.iloc[0]) - 1) * 100, 1))


def count_new_highs(ticker: str, period_start: str, period_end: str,
                    history_start: str = "1950-01-01") -> int:
    """Count new all-time closing highs set during [period_start, period_end]."""
    all_prices = fetch_prices(ticker, history_start, period_end)
    if all_prices.empty:
        return 0

    prior = all_prices[:period_start]
    period = all_prices[period_start:period_end]
    running_max = float(prior.max()) if not prior.empty else 0.0

    count = 0
    for price in period:
        if price > running_max:
            count += 1
            running_max = price
    return count


def get_win_streak(ticker: str, quarter: str, year: int) -> int:
    """Count consecutive positive quarters up to and including the given quarter."""
    q_order = ['Q1', 'Q2', 'Q3', 'Q4']
    streak = 0
    current_q = quarter.upper()
    current_y = year

    for _ in range(24):  # look back up to 6 years max
        start, end = get_quarter_dates(current_q, current_y)
        prices = fetch_prices(ticker, start, end)
        if prices.empty:
            break
        if pct_return(prices) > 0:
            streak += 1
        else:
            break
        idx = q_order.index(current_q)
        if idx == 0:
            current_q = 'Q4'
            current_y -= 1
        else:
            current_q = q_order[idx - 1]

    return streak


def get_all_market_data(quarter: str, year: int) -> dict:
    """
    Collect all financial metrics for the quarterly equity report.

    Returns dict with:
        quarter, year, quarter_name,
        acwi_return, acwi_ytd, acwi_record_highs_ytd,
        sp500_return, sp500_ytd, sp500_record_highs_q,
        sp500_record_highs_ytd, sp500_win_streak,
        fed_rate_start, fed_rate_end, fed_rate_change (if FRED available),
        errors (list of non-fatal warnings)
    """
    q = quarter.upper()
    q_start, q_end = get_quarter_dates(q, year)
    ytd_start = f"{year}-01-01"

    result: dict = {
        'quarter': q,
        'year': year,
        'quarter_name': QUARTER_NAMES[q],
        'errors': [],
    }

    # MSCI ACWI proxy — iShares MSCI ACWI ETF
    try:
        acwi_q = fetch_prices('ACWI', q_start, q_end)
        acwi_ytd = fetch_prices('ACWI', ytd_start, q_end)
        result['acwi_return'] = pct_return(acwi_q)
        result['acwi_ytd'] = pct_return(acwi_ytd)
        result['acwi_record_highs_ytd'] = count_new_highs('ACWI', ytd_start, q_end)
    except Exception as e:
        result['errors'].append(f"ACWI: {e}")
        result.update(acwi_return=None, acwi_ytd=None, acwi_record_highs_ytd=None)

    # S&P 500
    try:
        spx_q = fetch_prices('^GSPC', q_start, q_end)
        spx_ytd = fetch_prices('^GSPC', ytd_start, q_end)
        result['sp500_return'] = pct_return(spx_q)
        result['sp500_ytd'] = pct_return(spx_ytd)
        result['sp500_record_highs_q'] = count_new_highs('^GSPC', q_start, q_end)
        result['sp500_record_highs_ytd'] = count_new_highs('^GSPC', ytd_start, q_end)
        result['sp500_win_streak'] = get_win_streak('^GSPC', q, year)
    except Exception as e:
        result['errors'].append(f"S&P 500: {e}")
        result.update(sp500_return=None, sp500_ytd=None, sp500_record_highs_q=None,
                      sp500_record_highs_ytd=None, sp500_win_streak=None)

    # FRED — Fed Funds Rate (optional)
    if FRED_AVAILABLE and os.getenv('FRED_API_KEY'):
        try:
            fred = Fred(api_key=os.getenv('FRED_API_KEY'))
            ff = fred.get_series('FEDFUNDS', q_start, q_end)
            if not ff.empty:
                result['fed_rate_start'] = round(float(ff.iloc[0]), 2)
                result['fed_rate_end'] = round(float(ff.iloc[-1]), 2)
                result['fed_rate_change'] = round(
                    result['fed_rate_end'] - result['fed_rate_start'], 2)
        except Exception as e:
            result['errors'].append(f"FRED: {e}")

    return _sanitize(result)


def format_for_prompt(data: dict) -> str:
    """Render market data as a readable block for the writer LLM prompt."""
    def p(val):
        if val is None:
            return "N/A"
        sign = '+' if val > 0 else ''
        return f"{sign}{val}%"

    lines = [
        f"Quarter: {data['quarter']} {data['year']}  ({data['quarter_name']} quarter of {data['year']})",
        "",
        f"MSCI ACWI ETF quarterly return    : {p(data.get('acwi_return'))}",
        f"MSCI ACWI ETF YTD return          : {p(data.get('acwi_ytd'))}",
        f"MSCI ACWI new all-time highs YTD  : {data.get('acwi_record_highs_ytd', 'N/A')}",
        "",
        f"S&P 500 quarterly total return    : {p(data.get('sp500_return'))}",
        f"S&P 500 YTD total return          : {p(data.get('sp500_ytd'))}",
        f"S&P 500 record highs this quarter : {data.get('sp500_record_highs_q', 'N/A')}",
        f"S&P 500 record highs YTD          : {data.get('sp500_record_highs_ytd', 'N/A')}",
        f"S&P 500 win streak (pos. quarters): {data.get('sp500_win_streak', 'N/A')} consecutive",
    ]

    if data.get('fed_rate_start') is not None:
        lines += [
            "",
            f"Fed Funds Rate: {data['fed_rate_start']}% → {data['fed_rate_end']}%"
            f"  (change: {data['fed_rate_change']:+.2f}%)",
        ]

    if data.get('errors'):
        lines += ["", "Data warnings: " + "; ".join(data['errors'])]

    return "\n".join(lines)
