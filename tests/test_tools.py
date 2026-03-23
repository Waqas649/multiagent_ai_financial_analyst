import pytest
import src.agents as agents


# ---------------------------------------------------------------------------
# _llm_call — uses module-level llm; monkeypatch it
# ---------------------------------------------------------------------------

def test_llm_call_returns_content(monkeypatch):
    class FakeLLM:
        def invoke(self, prompt):
            class Resp:
                content = "hello"
            return Resp()

    monkeypatch.setattr(agents, "llm", FakeLLM())
    assert agents._llm_call("test prompt") == "hello"


def test_llm_call_falls_back_to_str(monkeypatch):
    class FakeLLM:
        def invoke(self, prompt):
            return 42  # no .content attribute

    monkeypatch.setattr(agents, "llm", FakeLLM())
    assert agents._llm_call("test prompt") == "42"


# ---------------------------------------------------------------------------
# _tavily_search — monkeypatch tavily_tool
# ---------------------------------------------------------------------------

def test_tavily_search_invoke(monkeypatch):
    class FakeTavily:
        def invoke(self, kwargs):
            return {"results": [{"title": "T", "url": "http://x.com", "content": "c"}]}

    monkeypatch.setattr(agents, "tavily_tool", FakeTavily())
    results = agents._tavily_search("test query")
    assert results == [{"title": "T", "url": "http://x.com", "content": "c"}]


def test_tavily_search_callable(monkeypatch):
    def fake_tavily(kwargs):
        return {"results": [{"title": "T", "url": "http://x.com", "content": "c"}]}

    monkeypatch.setattr(agents, "tavily_tool", fake_tavily)
    results = agents._tavily_search("test query")
    assert results == [{"title": "T", "url": "http://x.com", "content": "c"}]


# ---------------------------------------------------------------------------
# create_news_researcher_agent
# ---------------------------------------------------------------------------

def test_news_researcher_returns_news_context(monkeypatch):
    monkeypatch.setattr(agents, "tavily_tool", lambda kwargs: {
        "results": [{"title": "Test", "url": "http://example.com", "content": "Example content"}]
    })

    class FakeLLM:
        def invoke(self, prompt):
            class Resp:
                content = "summarised news"
            return Resp()

    monkeypatch.setattr(agents, "llm", FakeLLM())

    researcher = agents.create_news_researcher_agent()
    out = researcher({"intent": "report", "quarter": "Q1", "year": 2025, "search_query": ""})
    assert "news_context" in out
    assert isinstance(out["news_context"], str)
