"""Built-in web search plugin (stub implementation).

This module ships a *stub* implementation that returns a structured
placeholder result without making real network requests.  In a production
deployment you would subclass :class:`WebSearchPlugin` and override
:meth:`execute` to call the search API of your choice (e.g. Bing, Brave,
SerpAPI).
"""

from __future__ import annotations

from typing import Any

from pawnlogic.plugins.base import Plugin, PluginResult


class WebSearchPlugin(Plugin):
    """Search the web for a query and return a list of results.

    The default implementation is a **stub** that returns a placeholder
    response.  Override :meth:`_search` in a subclass to integrate a real
    search backend.
    """

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Searches the web for the given query and returns a summary of "
            "the top results."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "query": {
                "type": "string",
                "description": "The search query string.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 5).",
            },
        }

    def _search(self, query: str, max_results: int) -> list[dict[str, str]]:
        """Perform the actual search and return raw result dicts.

        Subclasses should override this method to call a real search API.
        The returned list should contain dicts with at least ``"title"``,
        ``"url"``, and ``"snippet"`` keys.

        The default implementation returns a stub result so the plugin
        can be used in tests and offline environments.
        """
        return [
            {
                "title": f"Stub result for '{query}'",
                "url": "https://example.com",
                "snippet": (
                    "This is a placeholder result. "
                    "Override WebSearchPlugin._search() to use a real search API."
                ),
            }
        ]

    def execute(self, **kwargs: Any) -> PluginResult:
        query: str = kwargs.get("query", "")
        if not query:
            return PluginResult(
                success=False, output="", error="'query' parameter is required."
            )
        max_results: int = int(kwargs.get("max_results", 5))
        try:
            results = self._search(query, max_results)
        except Exception as exc:
            return PluginResult(success=False, output="", error=str(exc))

        lines = []
        for i, item in enumerate(results, 1):
            lines.append(f"{i}. {item.get('title', '')}")
            lines.append(f"   URL: {item.get('url', '')}")
            lines.append(f"   {item.get('snippet', '')}")
        output = "\n".join(lines)
        return PluginResult(
            success=True,
            output=output,
            data={"query": query, "results": results},
        )
