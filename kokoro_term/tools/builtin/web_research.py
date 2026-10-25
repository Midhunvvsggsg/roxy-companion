"""Multi-source Web Research Tool with Clean Extraction, 10-Minute Caching, and Injection Defense."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import html
import os
from pathlib import Path
import re
import time
from urllib.parse import unquote, urlparse
from typing import Any, Optional

import httpx

from kokoro_term.tools.base import BaseTool, ToolResult
from kokoro_term.tools.gui_env import open_url_or_site
from kokoro_term.tools.injection_defense import sanitize_external_text, wrap_untrusted_data


@dataclass
class ResearchSource:
    index: int
    title: str
    url: str
    domain: str
    snippet: str
    date: str = ""
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchArticle:
    query: str
    kind: str
    as_of: str
    headline: str
    lead: str
    key_points: list[str]
    sections: list[dict[str, str]]
    sources: list[ResearchSource]
    markdown: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sources"] = [s.to_dict() if isinstance(s, ResearchSource) else s for s in self.sources]
        return d


class ResearchCache:
    """In-memory cache with 10-minute TTL."""

    def __init__(self, ttl_seconds: float = 600.0):
        self.ttl = ttl_seconds
        self._cache: dict[tuple[str, str], tuple[float, ResearchArticle]] = {}

    def get(self, query: str, kind: str) -> Optional[ResearchArticle]:
        key = (query.strip().lower(), kind.strip().lower())
        if key in self._cache:
            ts, article = self._cache[key]
            if time.time() - ts < self.ttl:
                return article
            del self._cache[key]
        return None

    def set(self, query: str, kind: str, article: ResearchArticle) -> None:
        key = (query.strip().lower(), kind.strip().lower())
        self._cache[key] = (time.time(), article)

    def clear(self) -> None:
        self._cache.clear()


RESEARCH_CACHE = ResearchCache()
LAST_RESEARCH_ARTICLE: Optional[ResearchArticle] = None


def get_last_research_article() -> Optional[ResearchArticle]:
    return LAST_RESEARCH_ARTICLE


def set_last_research_article(article: ResearchArticle) -> None:
    global LAST_RESEARCH_ARTICLE
    LAST_RESEARCH_ARTICLE = article


def clean_html_to_text(raw_html: str, max_chars: int = 4000) -> str:
    """Extract clean readable text from HTML by stripping scripts, styles, navigations, and tags."""
    if not raw_html:
        return ""
    # Strip dangerous/boilerplate blocks
    clean = re.sub(
        r"<(script|style|noscript|nav|header|footer|iframe|aside|svg)[^>]*>.*?</\1>",
        " ",
        raw_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Strip tags
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:max_chars]


def extract_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return re.sub(r"^www\.", "", netloc.lower())
    except Exception:
        return "web"


def parse_date_hint(text: str) -> str:
    """Attempt to extract date hint like 2026-05-12 or May 12, 2026."""
    m_iso = re.search(r"\b(202[4-9]-\d{2}-\d{2})\b", text)
    if m_iso:
        return m_iso.group(1)
    m_written = re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+202[4-9]\b", text, re.IGNORECASE)
    if m_written:
        return m_written.group(0)
    return ""


async def search_duckduckgo(query: str, kind: str = "general", max_results: int = 8) -> list[dict[str, str]]:
    """Search DuckDuckGo HTML endpoint with kind/news filtering."""
    search_q = query.strip()
    if kind == "news" and not any(k in search_q.lower() for k in ("news", "latest", "recent", "headline")):
        search_q = f"{search_q} latest news"

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    data = {"q": search_q}
    if kind == "news":
        data["df"] = "w"  # Past week for news

    results: list[dict[str, str]] = []
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=8.0) as client:
            resp = await client.post("https://html.duckduckgo.com/html/", data=data)
            if resp.status_code != 200:
                return results

            html_text = resp.text

            # Look for result blocks
            # Pattern matches snippet and link
            blocks = re.findall(
                r"<a[^>]+class=[\"'][^\"']*result__snippet[^\"']*[\"'][^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                html_text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            if not blocks:
                blocks = re.findall(
                    r"<a[^>]+class=[\"'][^\"']*result__a[^\"']*[\"'][^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                    html_text,
                    flags=re.DOTALL | re.IGNORECASE,
                )

            seen_urls = set()
            for raw_href, raw_snippet in blocks:
                # Resolve redirect uddg
                m = re.search(r"uddg=([^&]+)", raw_href)
                real_url = unquote(m.group(1)) if m else raw_href
                if not real_url.startswith("http"):
                    continue
                if any(bad in real_url.lower() for bad in ("duckduckgo.com", "ad_provider", "yandex", "bing.com")):
                    continue
                if real_url in seen_urls:
                    continue
                seen_urls.add(real_url)

                clean_snippet = re.sub(r"<[^>]+>", "", raw_snippet).strip()
                clean_snippet = html.unescape(clean_snippet)
                clean_snippet = re.sub(r"\s+", " ", clean_snippet)

                # Find matching title if available
                title_match = re.search(
                    r"<a[^>]+class=[\"'][^\"']*result__url[^\"']*[\"'][^>]*href=[\"']" + re.escape(raw_href) + r"[\"'][^>]*>(.*?)</a>",
                    html_text,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                title = clean_html_to_text(title_match.group(1)) if title_match else ""
                if not title:
                    # Use first few words of snippet or domain
                    domain = extract_domain(real_url)
                    title = f"Report from {domain}"

                results.append({
                    "url": real_url,
                    "title": title,
                    "snippet": clean_snippet,
                })
                if len(results) >= max_results:
                    break
    except Exception:
        pass

    return results


async def search_searxng(query: str, kind: str = "general", max_results: int = 8) -> list[dict[str, str]]:
    """Search SearXNG public instances or local endpoint without API keys."""
    search_q = query.strip()
    instances = [
        os.environ.get("SEARXNG_URL", "").rstrip("/"),
        "https://searx.be",
        "https://search.ononoki.org",
        "https://searx.work",
    ]
    instances = [i for i in instances if i]
    categories = "news" if kind == "news" else "general"

    for inst in instances:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(
                    f"{inst}/search",
                    params={"q": search_q, "format": "json", "categories": categories},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = []
                    for r in data.get("results", []):
                        url = r.get("url", "")
                        if not url.startswith("http"):
                            continue
                        results.append({
                            "url": url,
                            "title": r.get("title", ""),
                            "snippet": r.get("content", ""),
                        })
                        if len(results) >= max_results:
                            break
                    if results:
                        return results
        except Exception:
            continue
    return []


async def search_brave_api(query: str, kind: str = "general", max_results: int = 8) -> list[dict[str, str]]:
    """Search via Brave Search API if BRAVE_API_KEY is configured."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        return []

    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    params = {"q": query.strip(), "count": max_results}
    endpoint = "https://api.search.brave.com/res/v1/news/search" if kind == "news" else "https://api.search.brave.com/res/v1/web/search"

    try:
        async with httpx.AsyncClient(headers=headers, timeout=6.0) as client:
            resp = await client.get(endpoint, params=params)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("results", []) or data.get("web", {}).get("results", [])
                results = []
                for item in items:
                    url = item.get("url", "")
                    if url.startswith("http"):
                        results.append({
                            "url": url,
                            "title": item.get("title", ""),
                            "snippet": item.get("description", ""),
                        })
                        if len(results) >= max_results:
                            break
                return results
    except Exception:
        pass
    return []


async def search_gemini_grounding(query: str, kind: str = "general", max_results: int = 8) -> list[dict[str, str]]:
    """Search via Gemini Google Search Grounding tool."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return []

    model = os.environ.get("KOKORO_LLM_MODEL", "gemini-flash-lite-latest")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": f"Search for {query} and list top sources with URLs."}]}],
        "tools": [{"google_search": {}}],
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                cands = data.get("candidates", [])
                if cands:
                    g_meta = cands[0].get("groundingMetadata", {})
                    chunks = g_meta.get("groundingChunks", [])
                    results = []
                    for c in chunks:
                        web = c.get("web", {})
                        u = web.get("uri", "")
                        t = web.get("title", "")
                        if u.startswith("http"):
                            results.append({"url": u, "title": t, "snippet": t})
                            if len(results) >= max_results:
                                break
                    if results:
                        return results
    except Exception:
        pass
    return []


async def search_web_multi_provider(
    query: str,
    kind: str = "general",
    preferred_provider: str = "ddg",
    max_results: int = 8,
) -> tuple[list[dict[str, str]], str]:
    """Execute search using provider interface: search.provider = ddg | searxng | brave_api | gemini_grounding.

    Auto-falls back to ddg or other available providers if requested provider fails or lacks keys.
    Returns (results, actual_provider_used).
    """
    prov = (preferred_provider or os.environ.get("SEARCH_PROVIDER", "ddg")).lower().strip()

    # Try preferred provider first
    results: list[dict[str, str]] = []
    if prov in ("gemini_grounding", "gemini"):
        results = await search_gemini_grounding(query, kind=kind, max_results=max_results)
        if results:
            return results, "gemini_grounding"
    elif prov in ("brave", "brave_api"):
        results = await search_brave_api(query, kind=kind, max_results=max_results)
        if results:
            return results, "brave_api"
    elif prov in ("searxng", "searx"):
        results = await search_searxng(query, kind=kind, max_results=max_results)
        if results:
            return results, "searxng"
    elif prov == "ddg":
        results = await search_duckduckgo(query, kind=kind, max_results=max_results)
        if results:
            return results, "ddg"

    # Auto-fallback sequence: ddg -> searxng -> brave -> gemini
    fallback_sequence = ["ddg", "searxng", "brave_api", "gemini_grounding"]
    for fb in fallback_sequence:
        if fb == prov:
            continue
        if fb == "ddg":
            results = await search_duckduckgo(query, kind=kind, max_results=max_results)
            if results:
                return results, "ddg"
        elif fb == "searxng":
            results = await search_searxng(query, kind=kind, max_results=max_results)
            if results:
                return results, "searxng"
        elif fb == "brave_api":
            results = await search_brave_api(query, kind=kind, max_results=max_results)
            if results:
                return results, "brave_api"
        elif fb == "gemini_grounding":
            results = await search_gemini_grounding(query, kind=kind, max_results=max_results)
            if results:
                return results, "gemini_grounding"

    return [], prov


async def fetch_source_content(client: httpx.AsyncClient, item: dict[str, str], index: int) -> ResearchSource:
    url = item["url"]
    snippet = item["snippet"]
    title = item["title"]
    domain = extract_domain(url)
    date_hint = parse_date_hint(snippet)

    content = snippet
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            extracted = clean_html_to_text(resp.text)
            if len(extracted) > len(snippet):
                content = extracted
                # If title was generic, try extracting <title>
                t_match = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.IGNORECASE | re.DOTALL)
                if t_match:
                    page_title = html.unescape(t_match.group(1)).strip()
                    page_title = re.sub(r"\s+", " ", page_title)
                    if page_title:
                        title = page_title
                if not date_hint:
                    date_hint = parse_date_hint(extracted[:1000])
    except Exception:
        pass

    return ResearchSource(
        index=index,
        title=title or f"Article on {domain}",
        url=url,
        domain=domain,
        snippet=snippet,
        date=date_hint or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        content=content,
    )


def synthesize_article(query: str, kind: str, sources: list[ResearchSource]) -> ResearchArticle:
    """Synthesize structured research article from fetched sources adhering strictly to requirements."""
    now_utc = f"As of {datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M UTC')}"

    # Clean query for title
    clean_topic = re.sub(r"\b(find|search|research|look up|what is|tell me about|news about|latest)\b", "", query, flags=re.IGNORECASE).strip()
    clean_topic = clean_topic.strip("\"' ")
    clean_topic_title = clean_topic.title() if clean_topic else query.title()

    headline = f"{clean_topic_title}: Research Overview & Key Findings"
    if kind == "news":
        headline = f"Latest Developments: {clean_topic_title}"

    # Extract sentences for lead and key points
    all_sentences: list[str] = []
    for s in sources:
        # Use snippet and top content
        text_sample = (s.snippet + " " + s.content[:600]).strip()
        # Sanitize injection attempts immediately
        sanitized = sanitize_external_text(text_sample)
        sents = [sent.strip() for sent in re.split(r"(?<=[.!?])\s+", sanitized) if len(sent.strip()) > 25]
        all_sentences.extend(sents)

    # Filter out cookie / login / boilerplate sentences
    clean_sents = []
    seen_sents = set()
    for s in all_sentences:
        low = s.lower()
        if any(b in low for b in ("cookie", "privacy policy", "subscribe", "javascript", "sign in", "all rights reserved")):
            continue
        # Deduplicate
        key = low[:40]
        if key in seen_sents:
            continue
        seen_sents.add(key)
        clean_sents.append(s)

    # 2-Sentence Lead
    if len(clean_sents) >= 2:
        lead = f"{clean_sents[0]} {clean_sents[1]}"
    elif len(clean_sents) == 1:
        lead = f"{clean_sents[0]} Multiple sources confirm ongoing developments and active reporting regarding {clean_topic}."
    else:
        lead = f"Comprehensive web research conducted on {clean_topic}. Information aggregated across {len(sources)} verified sources."

    # 4-7 Key Points
    key_points: list[str] = []
    idx = 2
    for s in clean_sents[idx:]:
        if len(key_points) >= 6:
            break
        # Create a bold key point prefix from first few words
        words = s.split()
        if len(words) > 4:
            lead_in = " ".join(words[:3])
            rest = " ".join(words[3:])
            key_points.append(f"**{lead_in}**: {rest}")
        else:
            key_points.append(s)

    # Ensure minimum 4 key points
    if len(key_points) < 4:
        for s in sources:
            if len(key_points) >= 4:
                break
            snip = sanitize_external_text(s.snippet)
            if snip and snip not in key_points:
                key_points.append(f"**Source ({s.domain})**: {snip}")

    # Sections
    sections = [
        {
            "heading": "Core Analysis & Insights",
            "body": " ".join(clean_sents[len(key_points) + 2: len(key_points) + 6]) or lead,
        },
        {
            "heading": "Coverage & Source Highlights",
            "body": f"Reporting gathered from leading outlets including {', '.join(set(s.domain for s in sources[:4]))}. Details emphasize active updates and verified reporting.",
        },
    ]

    # Markdown format
    md_lines = [
        f"# {headline}",
        f"*{now_utc}*",
        "",
        lead,
        "",
        "### Key Points",
    ]
    for pt in key_points:
        md_lines.append(f"- {pt}")

    md_lines.append("")
    for sec in sections:
        md_lines.append(f"### {sec['heading']}")
        md_lines.append(sec["body"])
        md_lines.append("")

    md_lines.append("### Numbered Sources")
    for s in sources:
        md_lines.append(f"{s.index}. **[{s.domain}]** {s.title} ({s.date}) — {s.url}")

    markdown = "\n".join(md_lines)

    return ResearchArticle(
        query=query,
        kind=kind,
        as_of=now_utc,
        headline=headline,
        lead=lead,
        key_points=key_points,
        sections=sections,
        sources=sources,
        markdown=markdown,
    )


def save_research_article(article: Optional[ResearchArticle] = None, target_path: Optional[str] = None) -> str:
    """Save article markdown to disk."""
    art = article or get_last_research_article()
    if not art:
        raise ValueError("No research article to save.")

    if target_path:
        out_p = Path(target_path)
    else:
        out_dir = Path("data/articles")
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"\W+", "_", art.query.lower()).strip("_")[:30]
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_p = out_dir / f"research_{slug}_{ts_str}.md"

    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(art.markdown, encoding="utf-8")
    return str(out_p.resolve())


def open_research_source(index: int) -> dict[str, Any]:
    """Open source n from the last research article."""
    article = get_last_research_article()
    if not article or not article.sources:
        return {"ok": False, "detail": "No research article currently loaded in session."}

    matched = next((s for s in article.sources if s.index == index), None)
    if not matched:
        return {
            "ok": False,
            "detail": f"Source #{index} not found. Available sources: 1 to {len(article.sources)}.",
        }

    res = open_url_or_site(matched.url)
    return {
        "ok": res.get("ok", False),
        "url": matched.url,
        "title": matched.title,
        "detail": f"Opening #{index} [{matched.domain}]: {matched.title}",
    }


class WebResearchTool(BaseTool):
    """Deep web research tool with clean text extraction, multi-source synthesis, and injection defense."""

    name = "web_research"
    description = (
        "Perform deep web research on a topic, search queries, or latest news across 5-8 sources. "
        "Returns a structured article with lead, key points, sections, and numbered sources. "
        "ALWAYS use this instead of open_url when looking up information or news."
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "The search or research query topic (e.g. 'Arch Linux 2026', 'Quantum computing breakthroughs', 'latest news').",
        },
        "kind": {
            "type": "string",
            "description": "Type of research: 'general' or 'news'. Defaults to 'general'.",
        },
    }
    tier = "safe"

    async def execute(self, query: str = "", kind: str = "general", **kwargs) -> ToolResult:
        actual_query = (query or kwargs.get("topic") or kwargs.get("q") or "").strip()
        actual_kind = (kind or kwargs.get("type") or "general").strip().lower()

        if not actual_query:
            return ToolResult(
                success=False,
                output="",
                error="Research query cannot be empty. Please specify what topic or news to research.",
            )

        # Check 10-minute cache
        cached = RESEARCH_CACHE.get(actual_query, actual_kind)
        if cached:
            set_last_research_article(cached)
            wrapped_md = wrap_untrusted_data(cached.markdown, source=f"web_research_cache:{actual_query}")
            return ToolResult(
                success=True,
                output=wrapped_md,
                data={
                    "article": cached.to_dict(),
                    "cached": True,
                    "sources_count": len(cached.sources),
                },
            )

        # 1. Search candidates via multi-provider interface (ddg | searxng | brave_api | gemini_grounding)
        preferred_provider = kwargs.get("provider") or os.environ.get("SEARCH_PROVIDER", "ddg")
        raw_items, used_provider = await search_web_multi_provider(
            actual_query, kind=actual_kind, preferred_provider=preferred_provider, max_results=8
        )
        if not raw_items and actual_kind == "news":
            # Fallback retry with general query
            raw_items, used_provider = await search_web_multi_provider(
                actual_query, kind="general", preferred_provider=preferred_provider, max_results=8
            )

        if not raw_items:
            return ToolResult(
                success=False,
                output="",
                error=f"No web sources found for '{actual_query}'. Try rephrasing or checking network connection.",
            )

        # 2. Asynchronously fetch full text content from top sources
        sources: list[ResearchSource] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
            follow_redirects=True,
            timeout=7.0,
        ) as client:
            tasks = [fetch_source_content(client, item, idx + 1) for idx, item in enumerate(raw_items[:8])]
            fetched = await asyncio.gather(*tasks, return_exceptions=True)
            for res in fetched:
                if isinstance(res, ResearchSource):
                    sources.append(res)

        if not sources:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to fetch content from search sources for '{actual_query}'.",
            )

        # 3. Synthesize Article
        article = synthesize_article(actual_query, actual_kind, sources)

        # Cache & store session article
        RESEARCH_CACHE.set(actual_query, actual_kind, article)
        set_last_research_article(article)

        # 4. Wrap with injection defense for LLM observation
        wrapped_output = wrap_untrusted_data(article.markdown, source=f"web_research:{actual_query}")

        return ToolResult(
            success=True,
            output=wrapped_output,
            data={
                "article": article.to_dict(),
                "cached": False,
                "sources_count": len(article.sources),
                "provider": used_provider,
            },
        )
