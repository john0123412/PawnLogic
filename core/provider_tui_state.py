"""Pure state transitions for the provider management TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ProviderTUIState:
    panel: str = "main"
    main_cursor: int = 0
    detail_provider: str = ""
    detail_cursor: int = 0
    detail_status: str = ""
    detail_status_style: str = ""
    detail_key_active: bool = False
    dialog: str | None = None
    dialog_cursor: int = 0
    wiz_fields_pending: tuple[Any, ...] = ()
    wiz_fields: list[str] = field(
        default_factory=lambda: ["", "", "openai", ""]
    )
    wiz_focus: int = 0
    wiz_fmt_open: bool = False
    wiz_fmt_cursor: int = 0
    wiz_error: str = ""
    wiz_status: str = ""
    wiz_status_style: str = ""
    model_all: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    model_selected: set[str] = field(default_factory=set)
    model_manual: list[str] = field(default_factory=list)
    model_cursor: int = 0
    model_viewport: int = 0
    model_provider: str = ""
    model_caller: str = "main"
    model_error: str = ""
    model_search: str = ""
    model_search_focus: bool = False
    model_filter_cache: tuple[str, list[tuple[str, dict[str, Any]]]] = field(
        default_factory=lambda: ("", [])
    )
    model_notice: list[str] = field(default_factory=list)
    model_save_exit: bool = False
    manage_models: list[str] = field(default_factory=list)
    manage_cursor: int = 0
    manage_provider: str = ""
    manage_status: str = ""
    manage_status_style: str = ""

    def filtered_models(self) -> list[tuple[str, dict[str, Any]]]:
        query = self.model_search.strip().lower()
        if not query:
            return self.model_all
        if self.model_filter_cache[0] != query:
            self.model_filter_cache = (
                query,
                [(mid, cfg) for mid, cfg in self.model_all if query in mid.lower()],
            )
        return self.model_filter_cache[1]

    def reset_wizard(self) -> None:
        self.wiz_fields = ["", "", "openai", ""]
        self.wiz_focus = 0
        self.wiz_fmt_open = False
        self.wiz_fmt_cursor = 0
        self.wiz_error = ""
        self.wiz_status = ""
        self.wiz_status_style = ""

    def open_detail(self, provider: str) -> None:
        self.detail_provider = provider
        self.detail_cursor = 0
        self.detail_status = ""
        self.detail_status_style = ""
        self.detail_key_active = False
        self.panel = "detail"

    def begin_model_selection(
        self,
        *,
        provider: str,
        caller: str,
        candidates: list[tuple[str, dict[str, Any]]],
        existing_ids: set[str],
        notices: list[str],
    ) -> None:
        self.model_all = candidates
        self.model_selected = {mid for mid, _ in candidates if mid in existing_ids}
        self.model_manual = []
        self.model_cursor = 0
        self.model_viewport = 0
        self.model_provider = provider
        self.model_caller = caller
        self.model_error = ""
        self.model_search = ""
        self.model_search_focus = False
        self.model_filter_cache = ("", [])
        self.model_notice = notices
        self.model_save_exit = False
        self.detail_status = ""
        self.panel = "models"

    def cancel_model_selection(self) -> None:
        self.panel = self.model_caller
        self.detail_status = "Model sync cancelled."
        self.detail_status_style = "class:warning"


__all__ = ["ProviderTUIState"]
