"""Unit tests for Section 3: Web Research, Multi-Source Extraction, 10-Min Cache, and UI Panels."""

import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from kokoro_term.tools.builtin.web_research import (
    ResearchArticle,
    ResearchCache,
    ResearchSource,
    WebResearchTool,
    clean_html_to_text,
    get_last_research_article,
    open_research_source,
    save_research_article,
    set_last_research_article,
    synthesize_article,
)
from kokoro_term.tools.registry import ToolRegistry
from kokoro_term.ui.app import ArticleFocusScreen, ArticlePanelWidget


class TestWebResearchExtractionAndSynthesis:
    def test_clean_html_to_text(self):
        """clean_html_to_text strips script, style, nav, footer, tags and decodes entities."""
        raw_html = """
        <html>
            <head>
                <style>body { background: black; }</style>
                <script>alert('hack');</script>
            </head>
            <body>
                <nav><a href="/">Home</a></nav>
                <header><h1>Header Title</h1></header>
                <article>
                    <h2>Python 3.14 Features &amp; Improvements</h2>
                    <p>Python 3.14 introduces a faster JIT compiler and tail-call optimization.</p>
                </article>
                <footer>&copy; 2026 Python Org</footer>
            </body>
        </html>
        """
        cleaned = clean_html_to_text(raw_html)
        assert "alert('hack')" not in cleaned
        assert "background: black" not in cleaned
        assert "Python 3.14 Features & Improvements" in cleaned
        assert "faster JIT compiler" in cleaned
        assert "<" not in cleaned and ">" not in cleaned

    def test_synthesize_article_format(self):
        """Article must format with headline, timestamp, 2-sentence lead, 4-7 key points, and numbered sources."""
        sources = [
            ResearchSource(
                index=1,
                title="Python 3.14 Released",
                url="https://python.org/news/314",
                domain="python.org",
                snippet="Python 3.14 has officially been released with major performance enhancements.",
                date="2026-10-15",
                content="Python 3.14 brings next-generation performance. It enhances memory layout and introduces deferred reference counting.",
            ),
            ResearchSource(
                index=2,
                title="Deep-dive into Python 3.14",
                url="https://lwn.net/Articles/python314",
                domain="lwn.net",
                snippet="LWN analysis of Python 3.14 interpreter speedups and ecosystem support.",
                date="2026-10-16",
                content="Benchmark results show 15% improvement across standard suites. Third-party packages report smooth migration.",
            ),
            ResearchSource(
                index=3,
                title="Pydantic and Fastapi in 3.14",
                url="https://tiangolo.com/blog/py314",
                domain="tiangolo.com",
                snippet="Framework compatibility with Python 3.14 is verified across top libraries.",
                date="2026-10-18",
                content="All major async frameworks are tested and verified. Security enhancements include stricter parsing.",
            ),
        ]

        article = synthesize_article("python 3.14 release", "general", sources)
        assert article.headline.startswith("Python 3.14 Release")
        assert "As of" in article.as_of
        assert len(article.lead) > 30
        assert 4 <= len(article.key_points) <= 7
        assert len(article.sources) == 3
        assert "### Numbered Sources" in article.markdown
        assert "1. **[python.org]**" in article.markdown


class TestWebResearchCacheAndTool:
    def test_research_cache_ttl(self):
        """Cache stores items for 10 minutes (600s) and expires afterwards."""
        cache = ResearchCache(ttl_seconds=0.1)
        dummy_art = ResearchArticle(
            query="test query",
            kind="general",
            as_of="2026-10-25",
            headline="Test",
            lead="Lead sentence.",
            key_points=["Point 1", "Point 2", "Point 3", "Point 4"],
            sections=[],
            sources=[],
            markdown="# Test",
        )
        cache.set("test query", "general", dummy_art)
        assert cache.get("test query", "general") is not None

        time.sleep(0.15)
        assert cache.get("test query", "general") is None

    @pytest.mark.asyncio
    async def test_tool_execution_and_caching(self):
        """Tool executes search, caches result, and returns cached version on repeat."""
        tool = WebResearchTool()
        dummy_sources = [
            ResearchSource(
                index=1,
                title="AI Milestone",
                url="https://news.ycombinator.com/item?id=123",
                domain="ycombinator.com",
                snippet="Breakthrough in local model inference speed.",
                date="2026-10-25",
                content="Local models run twice as fast.",
            ),
            ResearchSource(
                index=2,
                title="Open Source Models",
                url="https://huggingface.co/blog/oss-ai",
                domain="huggingface.co",
                snippet="Hugging Face announces new model suite.",
                date="2026-10-25",
                content="New weights are accessible to everyone.",
            ),
        ]

        with patch("kokoro_term.tools.builtin.web_research.search_duckduckgo") as mock_search, \
             patch("kokoro_term.tools.builtin.web_research.fetch_source_content") as mock_fetch:
            mock_search.return_value = [
                {"url": "https://news.ycombinator.com/item?id=123", "title": "AI Milestone", "snippet": "Breakthrough in local model inference speed."},
                {"url": "https://huggingface.co/blog/oss-ai", "title": "Open Source Models", "snippet": "Hugging Face announces new model suite."},
            ]
            mock_fetch.side_effect = dummy_sources

            # First run: live search
            res1 = await tool.execute(query="local ai breakthroughs", kind="general")
            assert res1.success is True
            assert res1.data["cached"] is False
            assert "<<<UNTRUSTED_EXTERNAL_DATA" in res1.output

            # Second run: cache hit
            res2 = await tool.execute(query="local ai breakthroughs", kind="general")
            assert res2.success is True
            assert res2.data["cached"] is True


class TestResearchArticleStorageAndOpening:
    def test_save_research_article(self, tmp_path):
        """Saving article writes valid Markdown file."""
        dummy_art = ResearchArticle(
            query="quantum",
            kind="general",
            as_of="October 25, 2026",
            headline="Quantum Computing in 2026",
            lead="Quantum computing reaches fault tolerance milestones.",
            key_points=["Point 1", "Point 2", "Point 3", "Point 4"],
            sections=[{"heading": "Details", "body": "Quantum systems operate at higher temperatures."}],
            sources=[ResearchSource(index=1, title="Nature Quantum", url="https://nature.com/quantum", domain="nature.com", snippet="Nature report.")],
            markdown="# Quantum Computing in 2026\n\nLead.",
        )
        out_file = str(tmp_path / "quantum_test.md")
        saved = save_research_article(dummy_art, out_file)
        assert os.path.exists(saved)
        with open(saved, "r", encoding="utf-8") as f:
            content = f.read()
            assert "# Quantum Computing in 2026" in content

    def test_open_research_source_by_index(self):
        """open_research_source resolves source index and calls open_url_or_site."""
        dummy_art = ResearchArticle(
            query="quantum",
            kind="general",
            as_of="October 25, 2026",
            headline="Quantum",
            lead="Lead.",
            key_points=[],
            sections=[],
            sources=[
                ResearchSource(index=1, title="Source 1", url="https://site1.org", domain="site1.org", snippet=""),
                ResearchSource(index=2, title="Source 2", url="https://site2.org", domain="site2.org", snippet=""),
            ],
            markdown="",
        )
        set_last_research_article(dummy_art)

        with patch("kokoro_term.tools.builtin.web_research.open_url_or_site") as mock_open:
            mock_open.return_value = {"ok": True, "detail": "Opened in browser"}

            res = open_research_source(2)
            assert res["ok"] is True
            assert res["url"] == "https://site2.org"
            mock_open.assert_called_once_with("https://site2.org")

            # Out of bounds
            res_bad = open_research_source(99)
            assert res_bad["ok"] is False


class TestToolRegistryAndRoutingMandate:
    def test_web_research_registered_and_safe(self):
        """WebResearchTool is registered in ToolRegistry and classified safe."""
        registry = ToolRegistry()
        tool = registry.get("web_research")
        assert tool is not None
        assert tool.tier == "safe"

    def test_prompt_mandate_routes_research_vs_open(self):
        """System prompt instructions mandate web_research for search/news and open_url only for open/go."""
        registry = ToolRegistry()
        prompt_doc = registry.generate_system_prompt_documentation()
        assert "WEB RESEARCH & SEARCH MANDATE" in prompt_doc
        assert "web_research" in prompt_doc
        assert "Only use `open_app`" in prompt_doc or "Only use open_app" in prompt_doc


class TestUIWidgets:
    def test_article_panel_widget_formatting(self):
        """ArticlePanelWidget formats headline, lead, and sources count."""
        dummy_art = ResearchArticle(
            query="space exploration",
            kind="news",
            as_of="October 25, 2026",
            headline="Latest Mars Mission Updates",
            lead="Rover identifies organic molecules.",
            key_points=["**Sample Collected**: Found in crater bed."],
            sections=[],
            sources=[ResearchSource(index=1, title="NASA", url="https://nasa.gov", domain="nasa.gov", snippet="")],
            markdown="",
        )
        widget = ArticlePanelWidget(dummy_art)
        widget.update_display()
        assert "Latest Mars Mission Updates" in widget.rendered_text
        assert "Rover identifies organic molecules" in widget.rendered_text

    def test_article_focus_screen_initialization(self):
        """ArticleFocusScreen loads article markdown and dismisses with escape."""
        dummy_art = ResearchArticle(
            query="test",
            kind="general",
            as_of="",
            headline="Title",
            lead="",
            key_points=[],
            sections=[],
            sources=[],
            markdown="# Full Research Markdown",
        )
        screen = ArticleFocusScreen(dummy_art)
        assert screen.article == dummy_art
        bindings = {b.key: b.action for b in screen.BINDINGS}
        assert "escape" in bindings
        assert bindings["escape"] == "dismiss"
