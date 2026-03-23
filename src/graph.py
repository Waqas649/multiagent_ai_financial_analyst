# graph.py

from typing import TypedDict
from langgraph.graph import StateGraph, END
from .agents import (
    create_supervisor_chain,
    create_data_collector_agent,
    create_news_researcher_agent,
    create_writer_chain,
    create_critique_chain,
)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ReportState(TypedDict):
    quarter:         str   # "Q1" | "Q2" | "Q3" | "Q4"
    year:            int   # e.g. 2025
    user_message:    str   # raw natural-language input from the user
    intent:          str   # "report" | "news_query" | "other" — set by supervisor
    search_query:    str   # extracted search query for news_query intent
    market_data:     dict  # output of data_collector
    news_context:    str   # output of news_researcher
    draft:           str   # current report draft
    critique:        str   # critiquer feedback
    revision_number: int   # how many writer passes have run
    next_step:       str   # supervisor routing decision
    chat_reply:      str   # supervisor reply for "other" and "news_query" intents
    messages:        list  # conversation history: [{"role": "user"|"assistant", "content": str}]


# ---------------------------------------------------------------------------
# Initialize chains (done once at import time)
# ---------------------------------------------------------------------------

supervisor_chain      = create_supervisor_chain()
data_collector_agent  = create_data_collector_agent()
news_researcher_agent = create_news_researcher_agent()
writer_chain          = create_writer_chain()
critique_chain        = create_critique_chain()


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def supervisor_node(state: ReportState) -> dict:
    print("\n=== SUPERVISOR ===")
    decision = supervisor_chain(state)
    print(f"  -> {decision['next_step']}")
    return decision


def data_collector_node(state: ReportState) -> dict:
    print("\n=== DATA COLLECTOR ===")
    result = data_collector_agent(state)
    print(f"  -> data fetched for {state['quarter']} {state['year']}")
    return result


def news_researcher_node(state: ReportState) -> dict:
    print("\n=== NEWS RESEARCHER ===")
    result = news_researcher_agent(state)
    print(f"  -> news context: {len(result.get('news_context', ''))} chars")
    return result


def writer_node(state: ReportState) -> dict:
    print("\n=== WRITER ===")
    result = writer_chain(state)
    print(f"  -> draft rev {result.get('revision_number')}: {len(result.get('draft', ''))} chars")
    return result


def critique_node(state: ReportState) -> dict:
    print("\n=== CRITIQUER ===")
    result = critique_chain(state)
    critique = result.get("critique", "")
    approved = "APPROVED" in critique.upper()
    print(f"  -> {'APPROVED' if approved else 'needs revision'}")
    return result


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_graph(checkpointer=None):
    workflow = StateGraph(ReportState)

    workflow.add_node("supervisor",      supervisor_node)
    workflow.add_node("data_collector",  data_collector_node)
    workflow.add_node("news_researcher", news_researcher_node)
    workflow.add_node("writer",          writer_node)
    workflow.add_node("critiquer",       critique_node)

    workflow.set_entry_point("supervisor")

    workflow.add_edge("data_collector",  "supervisor")
    workflow.add_edge("news_researcher", "supervisor")
    workflow.add_edge("writer",          "critiquer")
    workflow.add_edge("critiquer",       "supervisor")

    workflow.add_conditional_edges(
        "supervisor",
        lambda state: state.get("next_step", "data_collector"),
        {
            "data_collector":  "data_collector",
            "news_researcher": "news_researcher",
            "writer":          "writer",
            "END":             END,
        },
    )

    return workflow.compile(checkpointer=checkpointer)


# No-checkpointer app — used by visualize_graph.py only
app = build_graph()
