# agents.py

import os
import json
from dotenv import load_dotenv
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_tavily import TavilySearch
from data_collector import get_all_market_data, format_for_prompt
from prompts import (
    news_researcher_prompt_template,
    writer_prompt_template,
    critique_prompt_template,
    EXAMPLE_REPORTS,
)

load_dotenv()

# ---------------------------------------------------------------------------
# LLM — NVIDIA
# ---------------------------------------------------------------------------

llm = ChatNVIDIA(
    model="openai/gpt-oss-120b",
    api_key=os.environ.get("NVIDIA_API_KEY"),
    temperature=1,
    top_p=1,
    max_tokens=4096,
)

# ---------------------------------------------------------------------------
# Tavily Search
# ---------------------------------------------------------------------------

tavily_tool = TavilySearch(
    max_results=5,
    topic="news",
    include_answer=False,
    include_raw_content=False,
    search_depth="advanced",
)


def _llm_call(prompt: str) -> str:
    response = llm.invoke(prompt)
    return response.content if hasattr(response, "content") else str(response)


def _tavily_search(query: str) -> list:
    try:
        if hasattr(tavily_tool, "invoke"):
            raw = tavily_tool.invoke({"query": query})
        else:
            raw = tavily_tool({"query": query})

        if isinstance(raw, dict):
            return raw.get("results", [])
        if isinstance(raw, str):
            parsed = json.loads(raw)
            return parsed.get("results", [])
        return []
    except Exception as e:
        print(f"[tavily] search error: {e}")
        return []


# ---------------------------------------------------------------------------
# SUPERVISOR
# ---------------------------------------------------------------------------

def _build_history_string(messages: list) -> str:
    """Format conversation history for inclusion in a prompt."""
    if not messages:
        return "No previous conversation."
    lines = []
    for m in messages[-10:]:  # last 10 turns to avoid context overflow
        role = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines)


def create_supervisor_chain():
    def supervisor_invoke(state: dict) -> dict:
        has_market_data = bool(state.get("market_data"))
        has_news        = bool(state.get("news_context", "").strip())
        has_draft       = bool(state.get("draft", "").strip())
        critique        = state.get("critique", "")
        revision        = state.get("revision_number", 0)
        user_message    = state.get("user_message", "").strip()
        intent          = state.get("intent", "")
        messages        = list(state.get("messages") or [])

        # First turn of a new request — classify intent
        if user_message and not intent:
            history = _build_history_string(messages)

            prompt = f"""You are a supervisor inside a Quarterly Equity Market Report Generator.

Conversation history:
{history}

Current user message: "{user_message}"

Classify into exactly one of three categories and respond accordingly:

1. REPORT — user wants to generate a quarterly equity market report
   (e.g. "Generate Q1 2025 report", "equity report for Q4 2024")
   → Reply with only the word:  report

2. NEWS_QUERY — user is asking a question about financial news, markets, or economic data
   (e.g. "What's happening with S&P 500?", "Latest Fed news", "How is NASDAQ doing?")
   → Reply with:  news_query: <a concise search query to find the answer>
   Example: news_query: S&P 500 latest performance and market news 2025

3. OTHER — greeting, small talk, follow-up question about the conversation, or unrelated question
   → Reply with a warm, conversational response. You may reference prior conversation history
     to answer questions like "what did I ask?" or "summarise our chat". If no history exists,
     mention you can generate quarterly equity market reports OR answer financial news questions.

Your response must be one of the three formats above — nothing else."""

            response = _llm_call(prompt).strip()
            print(f"[supervisor] intent response: {response[:100]}")

            # Append user turn to history immediately
            messages.append({"role": "user", "content": user_message})

            if response.lower().startswith("news_query:"):
                search_query = response[len("news_query:"):].strip()
                return {
                    "next_step":    "news_researcher",
                    "intent":       "news_query",
                    "search_query": search_query,
                    "messages":     messages,
                }

            if response.lower() == "report":
                return {"next_step": "data_collector", "intent": "report", "messages": messages}

            # OTHER — conversational reply; append assistant turn too
            messages.append({"role": "assistant", "content": response})
            return {"next_step": "END", "intent": "other", "chat_reply": response, "messages": messages}

        # news_query path — supervisor synthesises the answer from search results
        if intent == "news_query" and has_news:
            news_context = state.get("news_context", "")
            prompt = f"""You are a knowledgeable financial assistant.

The user asked: "{user_message}"

Here are the latest search results to help you answer:
{news_context}

Write a clear, concise, well-structured answer based on the search results above.
Be factual. Cite sources where relevant. Keep it conversational but informative."""
            reply = _llm_call(prompt)
            print(f"[supervisor] news_query reply: {reply[:80]}…")
            messages.append({"role": "assistant", "content": reply.strip()})
            return {"next_step": "END", "chat_reply": reply.strip(), "messages": messages}

        # Deterministic routing for the report pipeline
        if not has_market_data:
            return {"next_step": "data_collector"}
        if not has_news:
            return {"next_step": "news_researcher"}
        if not has_draft:
            return {"next_step": "writer"}
        if "APPROVED" in critique.upper():
            # Append the completed report to history
            draft = state.get("draft", "")
            if draft and (not messages or messages[-1].get("content") != draft):
                messages.append({"role": "assistant", "content": f"[Report generated]\n{draft}"})
            return {"next_step": "END", "messages": messages}
        if critique and revision < 2:
            return {"next_step": "writer"}
        if revision >= 2:
            return {"next_step": "END"}

        return {"next_step": "writer"}

    return supervisor_invoke


# ---------------------------------------------------------------------------
# DATA COLLECTOR (no LLM — pure yfinance/fredapi)
# ---------------------------------------------------------------------------

def create_data_collector_agent():
    def data_collector_invoke(state: dict) -> dict:
        quarter = state.get("quarter", "Q1")
        year    = state.get("year", 2025)
        print(f"[data_collector] Fetching data for {quarter} {year}...")
        data = get_all_market_data(quarter, year)
        if data.get("errors"):
            print(f"[data_collector] Warnings: {data['errors']}")
        return {"market_data": data}

    return data_collector_invoke


# ---------------------------------------------------------------------------
# NEWS RESEARCHER (Tavily) — context-aware for both report and news_query
# ---------------------------------------------------------------------------

def create_news_researcher_agent():
    def news_researcher_invoke(state: dict) -> dict:
        intent       = state.get("intent", "report")
        search_query = state.get("search_query", "").strip()
        quarter      = state.get("quarter", "Q1")
        year         = state.get("year", 2025)

        if intent == "news_query" and search_query:
            # Use the user's question as the search query directly
            queries = [search_query]
        else:
            # Standard report queries based on quarter/year
            queries = [
                f"S&P 500 stock market performance {quarter} {year}",
                f"global equity markets MSCI ACWI {quarter} {year}",
                f"Federal Reserve interest rate decision {quarter} {year}",
                f"stock market key themes drivers {year}",
            ]

        all_results = []
        for q in queries:
            print(f"[news_researcher] Searching: {q}")
            results = _tavily_search(q)
            for r in results[:3]:
                title   = r.get("title", "")
                content = r.get("content", "")[:500]
                url     = r.get("url", "")
                all_results.append(f"• {title} ({url}): {content}")

        search_text = "\n".join(all_results) if all_results else "No search results available."

        if intent == "news_query":
            # Store raw results — query_responder will synthesise the answer
            return {"news_context": search_text}

        # Report path — summarise for the writer
        prompt = news_researcher_prompt_template.format(
            quarter=quarter,
            year=year,
            search_results=search_text,
        )
        summary = _llm_call(prompt)
        return {"news_context": summary}

    return news_researcher_invoke


# ---------------------------------------------------------------------------
# WRITER
# ---------------------------------------------------------------------------

def create_writer_chain():
    def writer_invoke(state: dict) -> dict:
        quarter      = state.get("quarter", "Q1")
        year         = state.get("year", 2025)
        market_data  = state.get("market_data", {})
        news_context = state.get("news_context", "")
        critique     = state.get("critique", "")

        prompt = writer_prompt_template.format(
            example_reports=EXAMPLE_REPORTS,
            quarter=quarter,
            year=year,
            market_data=format_for_prompt(market_data),
            news_context=news_context,
            critique=critique or "None — this is the first draft.",
        )
        draft    = _llm_call(prompt)
        revision = state.get("revision_number", 0) + 1
        return {"draft": draft.strip(), "revision_number": revision}

    return writer_invoke


# ---------------------------------------------------------------------------
# CRITIQUER
# ---------------------------------------------------------------------------

def create_critique_chain():
    def critique_invoke(state: dict) -> dict:
        draft       = state.get("draft", "")
        market_data = state.get("market_data", {})
        revision    = state.get("revision_number", 0)

        if revision >= 2:
            return {"critique": "APPROVED — maximum revisions reached."}

        prompt = critique_prompt_template.format(
            market_data=format_for_prompt(market_data),
            draft=draft,
            example_reports=EXAMPLE_REPORTS,
        )
        feedback = _llm_call(prompt)
        return {"critique": feedback.strip()}

    return critique_invoke

