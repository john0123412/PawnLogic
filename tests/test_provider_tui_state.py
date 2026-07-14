"""Deterministic provider TUI state-transition tests."""

from core.provider_tui_state import ProviderTUIState


def test_model_filter_is_case_insensitive_and_cached():
    state = ProviderTUIState(
        model_all=[("GPT-5", {}), ("claude-sonnet", {}), ("gpt-mini", {})],
        model_search="gPt",
    )
    first = state.filtered_models()
    assert [name for name, _ in first] == ["GPT-5", "gpt-mini"]
    assert state.filtered_models() is first


def test_reset_wizard_restores_deterministic_defaults():
    state = ProviderTUIState(
        wiz_fields=["custom", "https://example.test", "anthropic", "secret"],
        wiz_focus=4,
        wiz_error="bad",
    )
    state.reset_wizard()
    assert state.wiz_fields == ["", "", "openai", ""]
    assert state.wiz_focus == 0
    assert state.wiz_error == ""


def test_begin_model_selection_preserves_only_existing_candidates():
    state = ProviderTUIState(detail_status="loading")
    candidates = [("alpha", {}), ("beta", {})]
    state.begin_model_selection(
        provider="custom",
        caller="detail",
        candidates=candidates,
        existing_ids={"beta", "missing"},
        notices=["filtered one embedding model"],
    )
    assert state.panel == "models"
    assert state.model_selected == {"beta"}
    assert state.model_provider == "custom"
    assert state.model_notice == ["filtered one embedding model"]
    assert state.detail_status == ""


def test_cancel_model_selection_returns_to_caller_with_status():
    state = ProviderTUIState(panel="models", model_caller="detail")
    state.cancel_model_selection()
    assert state.panel == "detail"
    assert state.detail_status == "Model sync cancelled."
    assert state.detail_status_style == "class:warning"
