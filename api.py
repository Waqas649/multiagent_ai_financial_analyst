# api.py

import re
import os
import uuid
import json
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

# ---------------------------------------------------------------------------
# Postgres checkpointer — set up once at startup
# ---------------------------------------------------------------------------

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from graph import build_graph

_DB_URI = os.getenv(
    "DATABASE_URL",
    "postgresql://{user}:{pw}@localhost:5432/{db}".format(
        user=os.getenv("POSTGRES_USER", "admin"),
        pw=os.getenv("POSTGRES_PASSWORD", "password"),
        db=os.getenv("POSTGRES_DB", "report_gen"),
    ),
)

_pg_conn   = psycopg.connect(_DB_URI, autocommit=True)
checkpointer = PostgresSaver(_pg_conn)
checkpointer.setup()          # creates checkpoint tables if they don't exist

graph_app = build_graph(checkpointer=checkpointer)

# ---------------------------------------------------------------------------

api = FastAPI(title="Equity Market Report API")

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    prompt: str
    quarter: str | None = None
    year: int | None = None
    max_iterations: int = 12
    thread_id: str | None = None   # pass to resume an existing conversation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_json_default(obj):
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    return str(obj)


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=safe_json_default)}\n\n"


def parse_quarter_input(text: str):
    text = text.strip()
    m = re.search(r'\b(Q[1-4])\s*(\d{4})\b', text, re.IGNORECASE)
    if m:
        return m.group(1).upper(), int(m.group(2))
    word_map = {'first': 'Q1', 'second': 'Q2', 'third': 'Q3', 'fourth': 'Q4'}
    m2 = re.search(
        r'\b(first|second|third|fourth)\s+quarter\s+(?:of\s+)?(\d{4})\b',
        text, re.IGNORECASE,
    )
    if m2:
        return word_map[m2.group(1).lower()], int(m2.group(2))
    return None, None

# ---------------------------------------------------------------------------
# /generate  — SSE stream
# ---------------------------------------------------------------------------

@api.post("/generate")
def generate(request: GenerateRequest):
    def event_stream():
        thread_id = request.thread_id or str(uuid.uuid4())

        quarter, year = parse_quarter_input(request.prompt)
        if not quarter:
            quarter = request.quarter or "Q1"
            year    = request.year    or 2025

        yield sse("resolved", {"quarter": quarter, "year": year, "thread_id": thread_id})

        config = {
            "configurable":    {"thread_id": thread_id},
            "recursion_limit": request.max_iterations,
        }

        # Resuming an existing thread: update user_message and reset
        # intent/next_step so the supervisor re-classifies the new message.
        # All other state (market_data, draft, messages, etc.) is preserved
        # from the checkpoint in Postgres.
        # New thread: send full initial state.
        if request.thread_id:
            input_state = {
                "user_message": request.prompt,
                "intent":       "",   # force re-classification
                "next_step":    "",
                "chat_reply":   "",
            }
        else:
            input_state = {
                "quarter":         quarter,
                "year":            year,
                "user_message":    request.prompt,
                "intent":          "",
                "search_query":    "",
                "market_data":     {},
                "news_context":    "",
                "draft":           "",
                "critique":        "",
                "revision_number": 0,
                "next_step":       "",
                "chat_reply":      "",
                "messages":        [],
            }

        final_draft       = ""
        final_market_data = {}
        chat_reply        = ""

        try:
            for step in graph_app.stream(input_state, config=config):
                node_name   = list(step.keys())[0]
                node_output = step[node_name]

                if isinstance(node_output, dict):
                    if node_output.get("draft") and len(node_output["draft"].strip()) > 50:
                        final_draft = node_output["draft"]
                    if node_output.get("market_data"):
                        final_market_data = node_output["market_data"]
                    if node_output.get("chat_reply"):
                        chat_reply = node_output["chat_reply"]

                yield sse("step", {"node": node_name, "data": node_output})

        except Exception as e:
            yield sse("error", {"message": str(e)})
            return

        yield sse("complete", {
            "status":      "done",
            "thread_id":   thread_id,
            "quarter":     quarter,
            "year":        year,
            "report":      final_draft,
            "market_data": final_market_data,
            "chat_reply":  chat_reply,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
