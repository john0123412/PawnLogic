#!/usr/bin/env python3
"""
PawnLogic CLI.

Multi-provider runtime, vision support, SQLite persistence, CoT guidance,
GSA skill archive, spec-driven execution, and GSD project state.
"""
import os, sys, shutil, argparse, asyncio, traceback, signal
from pawnlogic.repl import (
    ReplSignalState,
    read_text_cache as _read_text_cache,
    restore_last_input_buffer as _restore_last_input_buffer,
    safe_write_history,
    terminal_notice,
    write_text_cache as _write_text_cache,
)
from pawnlogic.startup import (
    default_pawnlogic_home as _default_pawnlogic_home,
    ensure_runtime_dir_writable,
    has_any_api_key,
    install_proxy as _install_proxy,
    manual_load_env as _manual_load_env,
)

if sys.version_info < (3, 10):
    print(
        "PawnLogic requires Python 3.10+. Current version: "
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        file=sys.stderr,
    )
    raise SystemExit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _fatal_startup_import_error(exc: ImportError) -> None:
    print(
        "PawnLogic failed to start: dependencies are missing or a config module could not be imported.\n"
        f"Error: {exc}\n"
        "For a source checkout, run: pip install -e .\n"
        "For a pip installation, run: pip install --upgrade pawnlogic",
        file=sys.stderr,
    )
    raise SystemExit(1)

# Exit sentinel returned by handle_slash when the user asks to exit.
# Re-exported from core.commands._common; the new system.py /exit handler
# returns the same sentinel object so identity comparison still works.
try:
    from core.commands._common import EXIT_SENTINEL as _EXIT_SENTINEL

    # Deferred render queue. /load and /resume set it; the main loop consumes
    # it before prompt_async. State lives in core/commands/_common.py.
    from core.commands._common import set_deferred_history, take_deferred_history

    # Provider/key helpers used by main()'s startup wizard. Their canonical
    # definitions live in core/commands/provider.py (loaded eagerly by
    # core.commands.__init__).
    from core.commands.provider import _run_key_wizard, _visible_models
except ImportError as _startup_import_error:
    _fatal_startup_import_error(_startup_import_error)

try:
    import readline  # noqa - not available on native Windows; tab completion is in main().
except ImportError:
    readline = None
from pathlib import Path

# P2 CLI UX: prompt_toolkit / rich availability detection.
# PROMPT_TOOLKIT_ENABLED=0/false forces the fallback path for E2E tests.
_FORCE_DISABLE_PT = os.getenv("PROMPT_TOOLKIT_ENABLED", "1").lower() in ("0", "false")

_HAS_PROMPT_TOOLKIT = False
_HAS_RICH = False
_PT_IMPORT_ERROR = None
_RICH_IMPORT_ERROR = None
try:
    if _FORCE_DISABLE_PT:
        raise ImportError("Prompt toolkit disabled by PROMPT_TOOLKIT_ENABLED=0")
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.formatted_text import StyleAndTextTuples
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.styles import Style as _PTStyle
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.shortcuts import CompleteStyle
    from prompt_toolkit.application import run_in_terminal as _pt_run_in_terminal
    from prompt_toolkit.patch_stdout import patch_stdout as _patch_stdout
    _HAS_PROMPT_TOOLKIT = True
except Exception as _e:
    _PT_IMPORT_ERROR = str(_e)
    PromptSession = None
    _patch_stdout = None
    _pt_run_in_terminal = None
    # Define dummy classes to prevent NameError in class definitions below
    class Completer:
        pass
    class Completion:
        pass
    class AutoSuggestFromHistory:
        pass


async def _terminal_notice(text: str) -> None:
    """Print a REPL notice without being erased by prompt_toolkit repainting."""
    runner = _pt_run_in_terminal if _HAS_PROMPT_TOOLKIT else None
    await terminal_notice(text, runner)

try:
    from rich.console import Console as _RichConsole
    from rich.markdown import Markdown as _RichMarkdown
    from rich.theme import Theme
    _pawn_rich_theme = Theme({
        "markdown.code": "dim cyan",
        "markdown.code_block": "dim cyan",
        "markdown.link": "underline cyan",
        "markdown.link_url": "dim blue",
    })
    _rich_console = _RichConsole(
        force_terminal=True,
        highlight=True,
        theme=_pawn_rich_theme,
        soft_wrap=True,
    )
    _HAS_RICH = True
except Exception as _e:
    _RICH_IMPORT_ERROR = str(_e)
    _rich_console = None

# Load .env at startup before importing config.
_PAWNLOGIC_DIR = _default_pawnlogic_home()
_ENV_PATH = _PAWNLOGIC_DIR / ".env"

try:
    from dotenv import load_dotenv
    if _ENV_PATH.exists():
        load_dotenv(dotenv_path=_ENV_PATH)
except ImportError:
    if _ENV_PATH.exists():
        print(
            "\033[93m  ⚠ Warning: python-dotenv is not installed; using the built-in .env parser.\033[0m",
            file=sys.stderr,
        )
        _manual_load_env(_ENV_PATH)

ENV_TEMPLATE = """# PawnLogic .env template.
#
# Copy this file to ~/.pawnlogic/.env or run `pawn` and use the first-run
# wizard. This file stores secrets only. MCP server declarations belong in
# mcp_configs.json.
#
# Security: never commit .env files.

# Recommended default provider.
# DeepSeek key URL: https://platform.deepseek.com
DEEPSEEK_API_KEY=

# Optional AI providers.
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
QWEN_API_KEY=
ZHIPU_API_KEY=
SILICON_API_KEY=
MOONSHOT_API_KEY=
GROQ_API_KEY=

# Custom provider examples. Add the provider with /provider before use.
XIAOMI_API_KEY=

# MCP tool keys. Only required when the matching MCP server is enabled.
TAVILY_API_KEY=
BROWSERBASE_API_KEY=
BROWSERBASE_PROJECT_ID=

# Advanced local endpoint.
# LOCAL_API_URL=http://localhost:11434/v1/chat/completions

# Optional runtime settings.
# PAWNLOGIC_DEFAULT_MODEL=ds-v4-flash
# PAWNLOGIC_LOG_LEVEL=INFO
"""

MCP_CONFIG_TEMPLATE = """{
  "mcpServers": {
    "tavily": {
      "command": "npx",
      "args": ["-y", "tavily-mcp"],
      "env": {
        "TAVILY_API_KEY": "${TAVILY_API_KEY}"
      }
    },
    "playwright": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp"]
    },
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/tmp"
      ]
    },
    "fetch": {
      "enabled": false,
      "command": "uvx",
      "args": ["mcp-server-fetch"],
      "allow_network_install": false
    }
  }
}
"""


def _ensure_runtime_templates(runtime_dir: Path) -> None:
    """Create user-editable config templates without enabling optional tools."""
    templates = {
        "env.example": ENV_TEMPLATE,
        "mcp_configs.example.json": MCP_CONFIG_TEMPLATE,
    }
    for name, content in templates.items():
        path = runtime_dir / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


PROXY_STATUS = _install_proxy()

try:
    import config  # kept for backward-compat attribute access
    from core.state import state as _runtime_state, set_output_mode
    from config import (
        VERSION, DYNAMIC_CONFIG,
        MODELS, DB_PATH, PROVIDERS,
        validate_api_key, list_vision_models,
    )
    from utils.ansi       import c, cp, BOLD, GRAY, CYAN, GREEN, YELLOW, RED, MAGENTA
    from core.session     import (
        AgentSession, STATE_FILENAME,
        attach_external_mcp_tools, detach_external_mcp_tools,
        TurnInterrupted,
    )
    from core.interrupts import turn_interrupt_handler
    from core.memory import init_db
    from core.persistence import session_load, _display_session_history
    # loguru logging module
    from core.logger import logger, setup_logger
except ImportError as _startup_import_error:
    _fatal_startup_import_error(_startup_import_error)

# ════════════════════════════════════════════════════════
# Interactive API key setup wizard.
# ════════════════════════════════════════════════════════





# ════════════════════════════════════════════════════════
# Help text.
# ════════════════════════════════════════════════════════

HELP_TEXT = f"""
{c(BOLD+CYAN, f"PawnLogic {VERSION} — Commands")}

{c(BOLD, "Conversation")}
  {c(YELLOW, "/mode")}            Toggle user-friendly/debug output
  {c(YELLOW, "/model [alias]")}   Switch model; only active providers with keys are shown
  {c(YELLOW, "/clear")}           Clear context while keeping pinned messages
  {c(YELLOW, "/context")}         Show context size and token estimate
  {c(YELLOW, "/pin [n]")}         Pin the last n messages
  {c(YELLOW, "/undo [n]")}        Undo recent turns
  {c(YELLOW, "/compact")}         Summarize and compact context
  {c(YELLOW, "/think <prompt>")}  Run one deeper reasoning turn
  {c(YELLOW, "/cd <path>")}       Change working directory
  {c(YELLOW, "/file <path>")}     Add a file to context

{c(BOLD, "API & Models")}
  {c(CYAN, "/setkey")}            Run API key setup again
  {c(CYAN, "/keys")}              Show configured key status
  {c(CYAN, "/provider")}          Open provider management panel
  {c(CYAN, "/provider list")}     List provider status
  {c(CYAN, "/provider add")}      Add a custom provider
  {c(CYAN, "/provider fetch <name>")} Fetch and select provider models
  {c(CYAN, "/provider update <name>")} Re-fetch provider models
  {c(CYAN, "/provider activate <name>")} Show selected provider models
  {c(CYAN, "/provider deactivate <name>")} Hide provider models
  {c(CYAN, "/provider test <model>")} Test provider connectivity

{c(BOLD, "Sessions & Memory")}
  {c(CYAN, "/save [name]")}       Save current session
  {c(CYAN, "/load <name|n>")}     Load a saved session
  {c(CYAN, "/sessions")}          List sessions
  {c(CYAN, "/resume [n]")}        Resume and display history
  {c(MAGENTA, "/memorize [topic]")} Save a summary to knowledge base
  {c(MAGENTA, "/knowledge [query]")} Search knowledge entries

{c(BOLD, "Runtime")}
  {c(GREEN, "/low")}   Light mode
  {c(YELLOW, "/mid")}  Default mode
  {c(MAGENTA, "/deep")} Deep mode
  {c(RED, "/max")}     Maximum mode
  {c(YELLOW, "/limits")} Show current limits
  {c(YELLOW, "/webstatus /browserstatus /docker /pwnenv")} Tool status

{c(BOLD, "Projects & History")}
  {c(YELLOW, "/init_project [desc]")} Create .pawn_state.md
  {c(YELLOW, "/state")}               Show .pawn_state.md
  {c(YELLOW, "/ctf status")}           Show CTF workspace metadata
  {c(YELLOW, "/ctf writeup")}          Export CTF writeup draft
  {c(CYAN, "/chat list [n]")}         List recent sessions
  {c(CYAN, "/chat find <keyword>")}   Search all sessions
  {c(CYAN, "/workspace status")}      Show workspace status

{c(YELLOW, "/exit")} Exit
"""


# ════════════════════════════════════════════════════════
# /init_project command implementation.
# ════════════════════════════════════════════════════════





# ════════════════════════════════════════════════════════
# GSA helper: /memo archive logic.
# ════════════════════════════════════════════════════════







# ════════════════════════════════════════════════════════
# /provider command handling.
# ════════════════════════════════════════════════════════




















# ════════════════════════════════════════════════════════
# Slash commands.
# ════════════════════════════════════════════════════════

async def handle_slash(cmd: str, session: AgentSession):
    """Thin entry shell. Parses the raw line into a CommandContext and
    forwards to the dispatcher in core.commands.
    """
    from core.commands import CommandContext, dispatch
    parts = cmd.strip().split(None, 2)
    ctx = CommandContext(
        verb = parts[0].lower(),
        arg  = parts[1].strip() if len(parts) > 1 else "",
        arg2 = parts[2].strip() if len(parts) > 2 else "",
        session = session,
    )
    return await dispatch(ctx)





# ════════════════════════════════════════════════════════
# main
# ════════════════════════════════════════════════════════

def _safe_write_history(path: str) -> None:
    """Write the readline history file without surfacing non-critical errors."""
    safe_write_history(readline, path)


# ════════════════════════════════════════════════════════
# P2.6: Claude Code style inline model selector.
# ════════════════════════════════════════════════════════



# ════════════════════════════════════════════════════════
# P2: rich Markdown renderer used by session.py.
# ════════════════════════════════════════════════════════

def render_agent_output(text: str) -> None:
    """
    Render agent text output.
    - With rich: detect Markdown structures and render them.
    - Without rich: print directly.
    """
    if not _HAS_RICH or not text.strip():
        print(text)
        return

    # Detect common Markdown structures.
    _md_indicators = ("```", "**", "| ", "## ", "- ", "1. ", "> ", "---", "===", "~~")
    has_md = any(indicator in text for indicator in _md_indicators)

    if has_md:
        try:
            _rich_console.print(_RichMarkdown(text, code_theme="monokai"))
            return
        except Exception:
            pass  # Fall back when rendering fails.

    print(text)


# ════════════════════════════════════════════════════════
# P2.6.4: PawnCompleter with built-in fuzzy matching.
#
# Root fix: FuzzyCompleter uses get_word_before_cursor() as its pattern. Since
# "/" is a non-word character, deleting back to "/" returns an empty string and
# recomputes start_position=0. That conflicts with the inner -N start_position
# and makes the menu disappear. This completer owns fuzzy matching and display
# highlighting directly.
# ════════════════════════════════════════════════════════

def _pawn_fuzzy_match(query: str, candidate: str):
    """
    Case-insensitive subsequence fuzzy match.
    Return (matched, hit_indices); hit_indices are highlighted positions.
    """
    q, c = query.lower(), candidate.lower()
    indices: list[int] = []
    ci = 0
    for qc in q:
        while ci < len(c) and c[ci] != qc:
            ci += 1
        if ci >= len(c):
            return False, []
        indices.append(ci)
        ci += 1
    return True, indices


class PawnCompleter(Completer):
    """
    PawnLogic completer with built-in fuzzy matching.

    - Activates for any input starting with /, including a single slash.
    - Matches examples such as /mdl -> /model and /model d -> /model ds-v4-flash.
    - Always replaces the whole slash command line with start_position=-len(text).
    - Highlights matched characters and keeps metadata on the right.
    """

    def __init__(
        self,
        words: list[str],
        meta_dict: dict[str, str] | None = None,
        dynamic_model_provider=None,
    ):
        self.words    = words
        self.meta_dict = meta_dict or {}
        self.dynamic_model_provider = dynamic_model_provider

    def _completion_words(self) -> tuple[list[str], dict[str, str]]:
        words = list(self.words)
        meta = dict(self.meta_dict)
        if self.dynamic_model_provider:
            try:
                for alias, minfo in self.dynamic_model_provider().items():
                    word = f"/model {alias}"
                    if word not in meta:
                        words.append(word)
                    meta[word] = minfo.get("desc", "")
            except Exception:
                pass
        return words, meta

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Only command input starts completion; regular text is ignored.
        if not text.startswith("/"):
            return

        results: list[tuple[bool, list[int], str]] = []  # (exact_prefix, indices, word)

        words, meta = self._completion_words()

        for word in words:
            matched, indices = _pawn_fuzzy_match(text, word)
            if not matched:
                continue
            # Exact prefixes are ranked first.
            exact = word.startswith(text)
            results.append((exact, indices, word))

        # Exact prefixes, then fuzzy matches, with lexical order inside each group.
        results.sort(key=lambda t: (not t[0], t[2]))

        for _, indices, word in results:
            # Build highlighted display fragments for matched characters.
            index_set = set(indices)
            display: StyleAndTextTuples = [
                (
                    "class:completion-menu.completion.character-match" if i in index_set else "",
                    ch,
                )
                for i, ch in enumerate(word)
            ]

            yield Completion(
                word,
                start_position=-len(text),   # replace the whole slash-command line
                display=display,
                display_meta=meta.get(word, ""),
            )


# ════════════════════════════════════════════════════════
# First-run wizard.
# ════════════════════════════════════════════════════════

def _has_any_api_key() -> bool:
    """Return whether at least one provider API key is present in process env.

    PROVIDERS is merged with custom_providers.json by explicit init_providers()
    during startup, so built-in and custom providers are handled uniformly
    without provider-name special cases.
    """
    return has_any_api_key(PROVIDERS)




def first_run_wizard() -> str | None:
    """
    First-run configuration wizard.
    Triggered when no usable API key exists. It guides provider selection and
    returns the model alias to enable for this run.
    """
    print("\n" + "═" * 56)
    print("  Welcome to PawnLogic. No API configuration was detected.")
    print("  First run requires one AI endpoint. This usually takes about a minute.")
    print("═" * 56 + "\n")

    choices = {
        "1": {
            "label": "DeepSeek",
            "api_format": "openai",
            "env_key": "DEEPSEEK_API_KEY",
            "default_alias": "ds-v4-flash",
            "default_model": "deepseek-v4-flash",
            "default_url": "https://api.deepseek.com/v1/chat/completions",
            "custom": False,
        },
        "2": {
            "label": "OpenAI",
            "api_format": "openai",
            "env_key": "OPENAI_API_KEY",
            "default_alias": "gpt-5.4-mini",
            "default_model": "gpt-5.4-mini",
            "default_url": "https://api.openai.com/v1/chat/completions",
            "custom": False,
        },
        "3": {
            "label": "Anthropic",
            "api_format": "anthropic",
            "env_key": "ANTHROPIC_API_KEY",
            "default_alias": "claude-sonnet",
            "default_model": "claude-sonnet-4-6",
            "default_url": "https://api.anthropic.com/v1/messages",
            "custom": False,
        },
        "4": {
            "label": "Custom OpenAI-compatible service",
            "api_format": "openai",
            "env_key": "",
            "default_alias": "",
            "default_model": "",
            "default_url": "https://api.example.com/v1/chat/completions",
            "custom": True,
        },
    }

    print("Step 1: Choose a provider")
    print("  1. DeepSeek (default, low cost)")
    print("  2. OpenAI")
    print("  3. Anthropic Claude")
    print("  4. Custom OpenAI-compatible service\n")

    while True:
        selection = input("Enter 1-4 (default 1): ").strip() or "1"
        if selection in choices:
            break
        print("  Enter 1, 2, 3, or 4.")

    choice = choices[selection]
    api_format = choice["api_format"]

    print(f"\nStep 2: Enter endpoint details ({choice['label']})")
    base_url = choice["default_url"]
    if choice["custom"]:
        base_url = input(f"  API Base URL\n  Press Enter to use default: {base_url}\n  > ").strip() or base_url

    api_key = ""
    while not api_key:
        api_key = input("\n  API Key (required): ").strip()
        if not api_key:
            print("  API key cannot be empty.")

    if choice["custom"]:
        default_model = choice["default_model"] or "my-model"
        model_id = input(
            f"\n  Model ID (press Enter to use default: {default_model}):\n  > "
        ).strip() or default_model

        alias = ""
        while not alias:
            alias = input(
                "\n  Give this model an alias, e.g. my-claude or my-deepseek:\n  > "
            ).strip()
            if not alias:
                print("  Alias cannot be empty.")
        env_key = f"{alias.upper().replace('-', '_').replace(' ', '_')}_API_KEY"
    else:
        alias = choice["default_alias"]
        model_id = choice["default_model"]
        env_key = choice["env_key"]

    # Append to .env without overwriting existing content.
    env_path = _ENV_PATH
    _PAWNLOGIC_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(_PAWNLOGIC_DIR, 0o700)
    except OSError:
        pass
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(f"\n# Generated by the PawnLogic first-run wizard\n{env_key}={api_key}\n")
    os.chmod(env_path, 0o600)

    if choice["custom"]:
        # Store structural config in custom_providers.json without the key.
        from core.provider_runtime import save_provider_with_rollback
        ok, save_err = save_provider_with_rollback(
            name=alias,
            prov_cfg={
                "base_url": base_url,
                "api_key_env": env_key,
                "label": alias,
                "api_format": api_format,
            },
            models_cfg={
                alias: {
                    "id": model_id,
                    "provider": alias,
                    "desc": f"User configured ({api_format})",
                    "color": "\033[37m",
                    "vision": False,
                }
            },
        )
        if not ok:
            print(f"\n✗ Failed to save provider config: {save_err}")

    # Reload .env so the current process can use the key immediately.
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)
    except ImportError:
        os.environ[env_key] = api_key

    print("\n✓ Configuration complete.")
    print(f"  Model alias: {alias}")
    print(f"  Automatically switched to /model {alias}\n")
    print("═" * 56 + "\n")
    return alias


def _prompt_startup_resume(session: AgentSession) -> bool:
    """Prompt for recent-session resume during interactive startup."""
    try:
        from core.memory import list_sessions as _list_sessions_startup
        recent_sessions = _list_sessions_startup(5)
        if not recent_sessions:
            return False
        print(c(BOLD, "\n  Recent sessions:"))
        for idx, row in enumerate(recent_sessions):
            name = row["name"] or "(untitled)"
            ts = str(row["updated_at"])[:16] if row["updated_at"] else ""
            msgs = row["msg_count"] if row["msg_count"] else 0
            model = row["model"] if row["model"] else ""
            print(
                c(GRAY, f"  [{idx+1}] ") +
                c(CYAN, name) +
                c(GRAY, f"  {ts}  {msgs} msgs  model={model}")
            )
        print(c(GRAY, "  [Enter] Start a new session"))
        try:
            resume_choice = input(cp(BOLD, "  Resume session [1-5/Enter]: ")).strip()
            if resume_choice.isdigit():
                idx = int(resume_choice) - 1
                if 0 <= idx < len(recent_sessions):
                    result = session_load(session, str(idx + 1))
                    if result.startswith("OK"):
                        print(c(GREEN, f"  ✓ {result}"))
                        set_deferred_history(session.messages)
                        return True
                    print(c(RED, f"  ✗ {result}"))
                else:
                    print(c(YELLOW, "  Selection out of range; starting a new session."))
            # Enter or any other input starts a new session.
        except (EOFError, KeyboardInterrupt):
            return False
    except Exception as exc:
        logger.warning("Startup session resume failed: {!r}", exc)
        if _runtime_state.user_mode:
            print(c(YELLOW, "  Could not load recent sessions; starting a new session."))
    return False


def _ensure_runtime_dir_writable(path: Path) -> None:
    ensure_runtime_dir_writable(path)
    _ensure_runtime_templates(path)


# ════════════════════════════════════════════════════════
# Stage-2: --eval single-shot execution mode
# ════════════════════════════════════════════════════════

async def _run_eval_mode(session: AgentSession, args, sink) -> None:
    """Single-shot run: execute one prompt and exit.

    Behavior:
      · If `--session <id>` is given, load that session first; on failure
        emit a structured error and exit non-zero.
      · Run `session.run_turn(args.eval)`. In human (default) mode, the
        agent's streaming output flows directly to stdout exactly as it
        would in the REPL.
      · In JSON mode the streaming output is captured (so the JSON wire
        stays clean), and a single structured `result` event is emitted
        from the final assistant message in `session.messages`.
      · Always shut down MCP subprocesses on exit.
    """
    is_json = bool(args.json)

    # 1. Optionally load a saved session before running.
    if args.session:
        result = session_load(session, args.session)
        if not result.startswith("OK"):
            if is_json:
                sink.print_json({
                    "type":  "error",
                    "stage": "session_load",
                    "query": args.session,
                    "detail": result,
                })
            else:
                sink.print(c(RED, f"  ✗ Session load failed: {result}"))
            detach_external_mcp_tools()
            sys.exit(2)

    # 2. Execute one turn.
    if is_json:
        # Suppress streaming prints so the JSON wire stays valid;
        # we re-emit the final assistant text as a structured event.
        import contextlib
        import io
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                session.run_turn(args.eval)
        except Exception as exc:  # noqa: BLE001
            sink.print_json({
                "type":   "error",
                "stage":  "run_turn",
                "detail": str(exc),
            })
            detach_external_mcp_tools()
            sys.exit(1)

        last_assistant = next(
            (m.get("content", "") for m in reversed(session.messages)
             if m.get("role") == "assistant" and m.get("content")),
            "",
        )
        sink.print_json({
            "type":         "result",
            "prompt":       args.eval,
            "response":     last_assistant,
            "session_id":   session.session_id,
            "model":        session.model_alias,
            "prompt_tokens":     session.total_prompt_tokens,
            "completion_tokens": session.total_completion_tokens,
            "tool_calls":        session.total_tool_calls,
        })
    else:
        # Human mode — let run_turn print directly, exactly as in the REPL.
        try:
            session.run_turn(args.eval)
        except Exception as exc:  # noqa: BLE001
            sink.print(c(RED, f"  ✗ {exc}"))
            if _runtime_state.debug_mode:
                traceback.print_exc()
            detach_external_mcp_tools()
            sys.exit(1)

    # 3. Clean shutdown of MCP subprocesses.
    detach_external_mcp_tools()
    sys.exit(0)


async def main():
    prompt_toolkit_enabled = _HAS_PROMPT_TOOLKIT
    # CLI argument parsing.
    parser = argparse.ArgumentParser(
        prog="pawn",
        description="PawnLogic — AI Agent Terminal",
        add_help=True,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Show detailed logs, tool calls, parser diagnostics, and reasoning streams.",
    )
    parser.add_argument(
        "--model", "-m",
        metavar="ALIAS",
        default=None,
        help="Start with a specific model alias (e.g. --model ds-v4-flash).",
    )
    parser.add_argument(
        "--eval", "-e",
        metavar="PROMPT",
        help="Run a single prompt and exit (non-interactive).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON (use with --eval or query commands).",
    )
    parser.add_argument(
        "--session", "-s",
        metavar="ID",
        help="Resume a specific session by ID (use with --eval).",
    )
    args = parser.parse_args()
    set_output_mode(debug_mode=bool(args.debug), quiet_mode=False)

    # Output sink stage-2 integration point. Select human or JSON output and
    # register the process-level singleton for dispatch() fallback injection.
    from core.output import HumanSink, JsonSink
    from core.commands._common import set_active_sink
    sink = JsonSink() if args.json else HumanSink()
    set_active_sink(sink)

    _is_test_mode = os.environ.get("PAWNLOGIC_TEST_MODE", "").lower() in ("1", "true", "yes")
    # Only check whether a usable key exists. _has_any_api_key covers built-in
    # and custom providers. Do not require ~/.pawnlogic/.env, because Docker,
    # CI, and Kubernetes commonly inject keys through process env only.
    _first_run_required = not _is_test_mode and not _has_any_api_key()

    if args.json and _first_run_required:
        sink.print_json({
            "type": "error",
            "stage": "startup",
            "detail": (
                "First run requires API setup. Run `pawn` once to complete the "
                "wizard, or set the corresponding API key environment variable "
                "before using --json."
            ),
        })
        sys.exit(2)

    try:
        _ensure_runtime_dir_writable(_PAWNLOGIC_DIR)
    except Exception as exc:
        detail = (
            f"Cannot write to runtime directory {_PAWNLOGIC_DIR}: {exc}\n"
            "Check HOME/PAWNLOGIC_HOME, directory permissions, or disk space."
        )
        if args.json:
            sink.print_json({"type": "error", "stage": "startup", "detail": detail})
        else:
            print(c(RED, f"  ✗ {detail}"))
        sys.exit(1)

    # Initialize loguru dual output. Default user mode and --json suppress
    # internal terminal logs; user-actionable failures are printed explicitly.
    # --debug shows INFO-level diagnostics on the terminal.
    setup_logger(
        stderr_level=(
            "INFO"
            if (_runtime_state.debug_mode and not args.json)
            else "CRITICAL"
        ),
        file_level="DEBUG",
    )
    logger.info(
        "PawnLogic {} starting | model={} debug={}",
        config.VERSION,
        args.model or config.DEFAULT_MODEL,
        _runtime_state.debug_mode,
    )

    try:
        init_db()
    except Exception as exc:
        detail = (
            f"Database initialization failed: {exc}\n"
            f"Ensure {_PAWNLOGIC_DIR} is writable, or set PAWNLOGIC_HOME to a writable directory."
        )
        logger.exception("init_db failed")
        if args.json:
            sink.print_json({"type": "error", "stage": "init_db", "detail": detail})
        else:
            print(c(RED, f"  ✗ {detail}"))
        sys.exit(1)
    attach_external_mcp_tools()
    from config.providers import init_providers
    init_providers(force=True)

    # First-run wizard.
    first_run_model_alias = None
    if _first_run_required:
        from core.state import state as _st
        _st.is_first_run = True
        try:
            first_run_model_alias = first_run_wizard()
        except (EOFError, KeyboardInterrupt):
            print(c(YELLOW, "\n  First-run setup cancelled. Use /setkey after startup to configure keys.\n"))
        from config.providers import init_providers
        init_providers(force=True)

    # Fall back to the key wizard if no key is configured.
    any_key = any(
        os.environ.get(p["api_key_env"], "")
        not in ("", "YOUR_API_KEY_HERE")
        for p in PROVIDERS.values()
        if p.get("api_key_env")
    )
    if not _is_test_mode and not any_key and not first_run_model_alias:
        configured = _run_key_wizard()
        if not configured:
            print(c(YELLOW,
                "\n  No key is configured, so the agent cannot call APIs.\n"
                "  You can use /setkey at any time or manually export KEY=sk-...\n"
            ))

    session = AgentSession()
    if first_run_model_alias and first_run_model_alias in MODELS:
        session.model_alias = first_run_model_alias

    # Apply --model startup flag
    if args.model:
        if args.model in MODELS:
            session.model_alias = args.model
        else:
            print(c(YELLOW, f"  ⚠ Unknown --model '{args.model}'; using the default model."))

    # --eval / --session single-shot mode. Intercept before decorative output so
    # JSON mode remains clean.
    if args.eval:
        await _run_eval_mode(session, args, sink)
        return


    # Startup tool availability check. CTF tools are shown only when at least
    # one exists, so regular users do not read optional tooling as a failure.
    CORE_TOOLS = ["gcc","g++","gdb","node","pandoc"]
    CTF_TOOLS = ["ROPgadget","checksec","objdump"]
    tool_tags = [c(GREEN, t) if shutil.which(t) else c(GRAY, f"{t}?") for t in CORE_TOOLS]
    ctf_tags = [c(GREEN, t) if shutil.which(t) else c(GRAY, f"{t}?") for t in CTF_TOOLS]
    if any(shutil.which(t) for t in CTF_TOOLS):
        tool_tags.append(c(GRAY, "ctf:") + " " + "  ".join(ctf_tags))

    proxy_line = (c(GREEN, f"  proxy : {PROXY_STATUS}") if PROXY_STATUS
                  else c(GRAY, "  proxy : not set"))

    key_ok, key_env = validate_api_key(session.model_alias)
    key_line = (c(GREEN,  f"  key   : {key_env} ✓")
                if key_ok else c(RED, f"  key   : {key_env} not configured  <- configure with /setkey"))

    state_exists = (Path(session.cwd) / STATE_FILENAME).exists()
    state_line   = (c(GREEN, f"  state : {STATE_FILENAME} detected; goal injected ✓")
                    if state_exists else
                    c(GRAY,  f"  state : no {STATE_FILENAME} (create with /init_project)"))

    vision_models = list_vision_models()
    vision_line   = c(
        GREEN if any(validate_api_key(m)[0] for m in vision_models) else GRAY,
        f"  vision: {', '.join(vision_models)}"
        + (" ✓" if any(validate_api_key(m)[0] for m in vision_models) else "  (key required)")
    )

    if _runtime_state.debug_mode:
        print(f"""
{c(BOLD+CYAN,"╔══════════════════════════════════════════════════════╗")}
{c(BOLD+CYAN,"║")}  {c(BOLD,f"PawnLogic {VERSION}")}  {c(GRAY,"· Plan · Vision · GSD · SQLite")}   {c(BOLD+CYAN,"║")}
{c(BOLD+CYAN,"║")}  {c(GRAY,"Multimodal · Spec-driven · Atomic commits · State.md · RAG")}  {c(BOLD+CYAN,"║")}
{c(BOLD+CYAN,"╚══════════════════════════════════════════════════════╝")}
  model : {c(MODELS[session.model_alias]['color'],session.model_alias)}  {c(GRAY,MODELS[session.model_alias]['desc'])}
  cwd   : {c(GRAY,session.cwd)}
  tier  : {c(YELLOW,"[MID]")}  tokens={DYNAMIC_CONFIG['max_tokens']}  ctx={DYNAMIC_CONFIG['ctx_max_chars']//1000}k  iter={DYNAMIC_CONFIG['max_iter']}
  tools : {"  ".join(tool_tags)}
  DB    : {c(GRAY,str(DB_PATH))}
{key_line}
{vision_line}
{state_line}
{proxy_line}
  {c(YELLOW,'/help')} commands  {c(GREEN,'/low')} {c(YELLOW,'/mid')} {c(MAGENTA,'/deep')} {c(RED,'/max')}  {c(CYAN,'/save /load')}  {c(MAGENTA,'/memorize')}  {c(YELLOW,'/init_project')}
""")
    else:
        key_sym = "✓" if key_ok else "✗"
        prx_sym = f" proxy={PROXY_STATUS}" if PROXY_STATUS else ""
        print(c(GRAY, f"PawnLogic {VERSION}  model={session.model_alias}  key{key_sym}{prx_sym}  /help  /mode debug"))

    # ════════════════════════════════════════════════════════
    # Startup session resume prompt.
    # ════════════════════════════════════════════════════════
    _startup_resume_done = _prompt_startup_resume(session)

    # ════════════════════════════════════════════════════════
    # P2: CLI UX — FuzzyCompleter + WordCompleter + Bottom Toolbar
    # ════════════════════════════════════════════════════════

    # Flat command list with gray descriptions on the right.
    _all_cmd_words = [
        "/mode", "/model", "/clear", "/context", "/pin", "/unpin", "/cd", "/file",
        "/undo", "/compact", "/think", "/ping",
        "/history", "/setkey", "/keys", "/save", "/load", "/resume", "/sessions", "/del",
        "/memorize", "/knowledge", "/forget", "/init_project", "/state",
        "/low", "/mid", "/deep", "/max", "/normal", "/limits",
        "/tokens", "/ctx", "/iter", "/toolsize", "/fetchsize",
        "/webstatus", "/browserstatus", "/pwnenv", "/stats", "/time", "/docker",
        "/worker", "/failures", "/memo", "/skills", "/skillpack", "/sp", "/ctf",
        "/chat", "/help", "/exit",
    ]

    _cmd_meta = {
        "/mode":          "Toggle user-friendly/debug output",
        "/model":         "Switch AI model (/model ds-v4-flash)",
        "/clear":         "Clear context while keeping pinned messages",
        "/context":       "Show context size and token estimate",
        "/pin":           "Pin recent messages (/pin msg 5 by index)",
        "/unpin":         "Clear all pinned messages",
        "/undo":          "Undo recent turns (default 1)",
        "/compact":       "Compact context with a lightweight summary",
        "/think":         "Single-turn reasoning mode (/think <prompt>)",
        "/ping":          "Keepalive request to refresh cache TTL",
        "/cd":            "Change working directory",
        "/file":          "Load a file into context",
        "/history":       "Show indexed message history",
        "/setkey":        "Run API key setup wizard again",
        "/keys":          "Show provider key status",
        "/save":          "Save current session to SQLite",
        "/load":          "Load a saved session",
        "/resume":        "Resume a recent session interactively or with /resume n",
        "/sessions":      "List saved sessions",
        "/del":           "Delete a session",
        "/memorize":      "Summarize conversation and save to knowledge base",
        "/knowledge":     "Search or list knowledge entries",
        "/forget":        "Delete a knowledge entry",
        "/init_project":  "Initialize .pawn_state.md project state",
        "/state":         "Show current project .pawn_state.md",
        "/low":           "Light mode (tokens=4k, ctx=40k)",
        "/mid":           "Development mode (tokens=8k, ctx=150k) <- default",
        "/deep":          "Full-power mode (tokens=32k, ctx=400k)",
        "/max":           "Maximum mode (tokens=32k, ctx=600k, iter=100, 60min)",
        "/normal":        "Reset to /mid",
        "/limits":        "Show all runtime limits",
        "/tokens":        "Set max_tokens",
        "/ctx":           "Set context limit",
        "/iter":          "Set max iterations",
        "/toolsize":      "Set tool output truncation size",
        "/fetchsize":     "Set web fetch truncation size",
        "/webstatus":     "Jina / Pandoc / Lynx tool status",
        "/browserstatus": "Scrapling browser tool status",
        "/pwnenv":        "CTF/Pwn toolchain integrity check",
        "/stats":         "Token usage for this session",
        "/time":          "Time budget (/time 300 = 5 minutes)",
        "/docker":        "Docker container management (status/images/ps/pull)",
        "/worker":        "Worker model selection",
        "/failures":      "View or clear failure records",
        "/memo":          "Manually archive a skill to GSA",
        "/skills":        "Show global skill archive directory",
        "/skillpack":     "Manage local skill packs (list/rescan/detail)",
        "/sp":            "Alias for /skillpack",
        "/ctf":           "Track CTF metadata and export writeup drafts",
        "/chat":          "Session browser (list/view/find/tag/link)",
        "/workspace":     "Workspace maintenance tools (status/cleanup)",
        "/help":          "Show help",
        "/exit":          "Exit PawnLogic",
    }

    # Merge top-level commands and subcommands. Model aliases are read live from
    # active providers with configured keys.
    _all_words = list(_all_cmd_words)
    _all_meta  = dict(_cmd_meta)
    # Common subcommands.
    for _sub in ("list", "view", "export", "find", "tag", "untag",
                 "bytag", "link", "unlink", "related"):
        _w = f"/chat {_sub}"
        _all_words.append(_w)
        _all_meta[_w] = f"Session {_sub}"
    for _sub in ("clear", "list"):
        _w = f"/failures {_sub}"
        _all_words.append(_w)
        _all_meta[_w] = f"Failure records {_sub}"
    _all_words.extend(["/worker auto", "/skills view", "/skills path", "/skills packs",
                       "/skillpack list", "/skillpack rescan", "/sp list", "/sp rescan",
                       "/sp sync", "/sp install",
                       "/ctf init", "/ctf status", "/ctf artifact", "/ctf remote",
                       "/ctf flag", "/ctf solved", "/ctf confirm", "/ctf writeup",
                       "/workspace status", "/workspace cleanup",
                       "/workspace cleanup plan", "/workspace cleanup execute",
                       "/workspace cleanup restore"])
    _all_meta["/worker auto"] = "Restore automatic worker routing"
    _all_meta["/skills view"] = "Show full skill file"
    _all_meta["/skills path"] = "Show skill file path"
    _all_meta["/skills packs"] = "List local skill packs under skills/"
    _all_meta["/skillpack list"] = "List all local skill packs"
    _all_meta["/skillpack rescan"] = "Rescan skills/"
    _all_meta["/sp list"] = "List all local skill packs"
    _all_meta["/sp rescan"] = "Rescan skills/"
    _all_meta["/sp sync"] = "Sync all git-backed skill packs"
    _all_meta["/sp install"] = "Install a new skill pack from a remote repository"
    _all_meta["/ctf init"] = "Initialize CTF workspace metadata"
    _all_meta["/ctf status"] = "Show CTF workspace metadata"
    _all_meta["/ctf artifact"] = "Record a CTF artifact"
    _all_meta["/ctf remote"] = "Record a CTF remote target"
    _all_meta["/ctf flag"] = "Record a CTF flag candidate"
    _all_meta["/ctf solved"] = "Mark a confirmed CTF flag as solved"
    _all_meta["/ctf confirm"] = "Alias for /ctf solved"
    _all_meta["/ctf writeup"] = "Export a CTF writeup draft"
    _all_meta["/workspace status"]            = "Show workspace overview"
    _all_meta["/workspace cleanup"]           = "Generate a cleanup plan"
    _all_meta["/workspace cleanup plan"]      = "Phase 0+1: backup and scan, then output a plan"
    _all_meta["/workspace cleanup execute"]   = "Phase 2+3: archive by plan and sync DB"
    _all_meta["/workspace cleanup restore"]   = "Restore workspace from the latest tar backup"
    # Docker subcommands.
    for _sub, _desc in [
        ("status", "Show Docker connection status"),
        ("images", "List local Docker images"),
        ("ps",     "Show currently running sandbox containers"),
        ("pull",   "Pull preset Pwn/environment images from the registry"),
        ("clean",  "Clean stopped containers and dangling images"),
    ]:
        _w = f"/docker {_sub}"
        _all_words.append(_w)
        _all_meta[_w] = _desc
    # Provider subcommands.
    for _sub, _desc in [
        ("list",   "List all provider status"),
        ("add",    "Register a custom provider interactively or add <alias> <url> <KEY> [anthropic]"),
        ("fetch",  "Fetch usable models and register selections"),
        ("update", "Re-fetch and update registered provider models"),
        ("activate", "Show this provider's selected models"),
        ("deactivate", "Hide this provider's models"),
        ("remove", "Delete a custom provider"),
        ("test",   "Test provider connectivity"),
    ]:
        _w = f"/provider {_sub}"
        _all_words.append(_w)
        _all_meta[_w] = _desc

    # readline history file path and last-submitted prompt cache.
    _history_path = str(_PAWNLOGIC_DIR / ".input_history")
    _last_input_path = _PAWNLOGIC_DIR / ".last_input"

    if prompt_toolkit_enabled:
        # Use PawnCompleter directly. It has built-in fuzzy matching.
        _pawn_completer = PawnCompleter(
            _all_words,
            meta_dict=_all_meta,
            dynamic_model_provider=_visible_models,
        )

        try:
            _pt_history = FileHistory(_history_path)
        except Exception:
            from prompt_toolkit.history import InMemoryHistory
            _pt_history = InMemoryHistory()

        # Bottom toolbar: model / tier / directory / token count / context percent.
        def _bottom_toolbar():
            _m = session.model_alias
            _tier = "MID"
            if DYNAMIC_CONFIG["max_tokens"] <= 4096:
                _tier = "LOW"
            elif DYNAMIC_CONFIG["max_iter"] >= 100:
                _tier = "MAX"
            elif DYNAMIC_CONFIG["max_tokens"] >= 32768:
                _tier = "DEEP"
            _tb = DYNAMIC_CONFIG.get("time_budget_sec", 0)
            _time_str = f"  ⏱ {_tb}s" if _tb > 0 else ""
            # Token count and context percentage with color thresholds.
            _tk = session.total_prompt_tokens + session.total_completion_tokens
            _ctx_used = sum(len(str(m.get("content", ""))) for m in session.messages)
            _ctx_max = DYNAMIC_CONFIG["ctx_max_chars"]
            _ctx_pct = min(100, int(_ctx_used * 100 / _ctx_max)) if _ctx_max else 0
            if _ctx_pct >= 90:
                _ctx_color = "ansired"
            elif _ctx_pct >= 70:
                _ctx_color = "ansiyellow"
            else:
                _ctx_color = "ansigreen"
            return HTML(
                f" <b>Model:</b> {_m}"
                f"  <b>Tier:</b> {_tier}"
                f"  <b>Tk:</b> {_tk:,}"
                f"  <b>Ctx:</b> <{_ctx_color}>{_ctx_pct}%</{_ctx_color}>"
                f"  <b>Dir:</b> {session.cwd}"
                f"  <b>Phase:</b> {session.current_phase}"
                f"{_time_str}"
            )

        # Transparent styling with no gray block artifacts.
        _pawn_style = _PTStyle.from_dict({
            "prompt": "ansigreen bold",
            "you": "bold",
            "completion-menu": "bg:default fg:#bbbbbb",
            "completion-menu.completion": "bg:default fg:#bbbbbb",
            "completion-menu.meta.completion": "bg:default fg:#666666",
            "completion-menu.completion.current": "bg:#333333 fg:#ffffff",
            "completion-menu.meta.completion.current": "bg:#333333 fg:#aaaaaa",
            "completion-menu.completion.character-match": "fg:#00d787 bold",
            "scrollbar.background": "bg:default",
            "scrollbar.button": "bg:default",
            "bottom-toolbar": "bg:#222222 fg:#cccccc",
        })

        # Intercept backspace to force completion refresh in slash-command mode.
        from prompt_toolkit.key_binding import KeyBindings
        _kb = KeyBindings()
        _ctrl_z_restore_state: dict[str, str] = {}

        @_kb.add('backspace')
        @_kb.add('c-h')  # compatible with some Linux terminal backspace values
        def _(event):
            b = event.app.current_buffer
            # 1. Perform the native delete-before-cursor action.
            if b.text:
                b.delete_before_cursor(1)

            # 2. If the buffer still starts with "/", force the completion menu
            # to re-open after prompt_toolkit updates the buffer.
            if b.text.startswith('/'):
                b.start_completion(select_first=False)

        @_kb.add('c-z')
        def _(event):
            last_input = _read_text_cache(_last_input_path)
            _restore_last_input_buffer(
                event.app.current_buffer,
                last_input,
                _ctrl_z_restore_state,
            )

        # ──────────────────────────────────────────────────────────

        _pt_session = PromptSession(
            completer=_pawn_completer,
            key_bindings=_kb,
            auto_suggest=AutoSuggestFromHistory(),
            history=_pt_history,
            complete_while_typing=True,
            complete_in_thread=False,
            complete_style=CompleteStyle.COLUMN,
            mouse_support=False,
            bottom_toolbar=_bottom_toolbar,
            reserve_space_for_menu=4,
        )

        if _runtime_state.debug_mode:
            print(c(GRAY, "  🐚 Tab completion enabled (advanced mode)"))
            if _HAS_RICH:
                print(c(GRAY, "  📝 Markdown rendering and code highlighting enabled"))
            elif _RICH_IMPORT_ERROR:
                print(c(YELLOW, f"  ⚠ rich failed to load: {_RICH_IMPORT_ERROR}"))
    else:
        # readline fallback mode.
        _ALL_COMMANDS = sorted(_all_words)

        def _completer_rl(text: str, state: int):
            line = readline.get_line_buffer()
            if line.startswith("/"):
                matches = [cmd for cmd in _ALL_COMMANDS if cmd.startswith(line)]
                if not matches:
                    matches = [cmd for cmd in _ALL_COMMANDS if cmd.startswith(text)]
            else:
                import glob
                matches = glob.glob(text + "*") if text else glob.glob("*")
                matches = [os.path.expanduser(m) + ("/" if os.path.isdir(m) else "") for m in matches]
            return matches[state] if state < len(matches) else None

        if readline is not None:
            readline.set_completer(_completer_rl)
            readline.set_completer_delims(" \t")
            readline.parse_and_bind("tab: complete")
            try:
                readline.read_history_file(_history_path)
            except FileNotFoundError:
                pass
            import atexit
            atexit.register(lambda: _safe_write_history(_history_path))

        if _runtime_state.debug_mode:
            print(c(GRAY, "  🐚 Tab completion enabled (basic mode)"))
            if _PT_IMPORT_ERROR:
                print(c(YELLOW, f"  ⚠ prompt_toolkit failed to load: {_PT_IMPORT_ERROR}"))
                print(c(YELLOW, f"     Python: {sys.executable}"))
                print(c(YELLOW, "     Fix: run pip install prompt_toolkit rich inside the venv"))
                print(c(YELLOW, "     Or reinstall with: pip install -e ."))

    # Main loop.
    _re_edit_default = ""     # after Ctrl+C, previous user text becomes prompt default
    _signal_state = ReplSignalState()

    def _restore_last_input_on_sigtstp(_signum, _frame):
        _signal_state.request_last_input_restore()

    _previous_sigtstp = None
    try:
        _previous_sigtstp = signal.getsignal(signal.SIGTSTP)
        signal.signal(signal.SIGTSTP, _restore_last_input_on_sigtstp)
    except Exception:
        _previous_sigtstp = None

    while True:
        try:
            if _signal_state.consume_last_input_restore():
                _cached_input = _read_text_cache(_last_input_path)
                if _cached_input:
                    _re_edit_default = _cached_input

            # ════════════════════════════════════════════════════════
            # Invisible-history fix: pre-render before any prompt_toolkit API:
            #   [1] _display_session_history prints ANSI output and flushes.
            #   [2] sys.stdout.flush() forces the physical write.
            #   [3] print("\n") reserves a blank line so prompt_async takes over
            #       below history content instead of repainting over it.
            # ════════════════════════════════════════════════════════
            if (_hist_msgs := take_deferred_history()) is not None:
                logger.debug("pre-render history: {} msgs", len(_hist_msgs))
                _display_session_history(_hist_msgs, show_recent=len(_hist_msgs))
                print("─" * 20 + " history context above " + "─" * 20)
                sys.stdout.flush()
                print("\n")  # reserve one physical line

            if prompt_toolkit_enabled:
                # Native async: patch_stdout keeps agent output from corrupting
                # the active input line.
                with _patch_stdout(raw=True):
                    raw = (await _pt_session.prompt_async(
                        [("class:prompt", "▶ "), ("class:you", "You > ")],
                        style=_pawn_style,
                        default=_re_edit_default,
                    )).strip()
            else:
                _label = _re_edit_default if _re_edit_default else ""
                raw = input(cp(BOLD+GREEN, "▶ ") + cp(BOLD, "You > ") + _label).strip()

            _re_edit_default = ""    # clear after consuming it
            _signal_state.submitted()
            if not raw:
                continue
            if raw.startswith("/"):
                # Fuzzy command typo correction.
                _cmd_parts = raw.split(None, 1)
                _cmd_verb  = _cmd_parts[0]
                _cmd_rest  = _cmd_parts[1] if len(_cmd_parts) > 1 else ""
                if _cmd_verb not in _all_cmd_words and len(_cmd_verb) >= 3:
                    import difflib
                    _close = difflib.get_close_matches(
                        _cmd_verb, _all_cmd_words, n=1, cutoff=0.7
                    )
                    if _close:
                        _corrected = _close[0]
                        raw = f"{_corrected} {_cmd_rest}".strip() if _cmd_rest else _corrected
                        print(c(YELLOW, f"  ✔ Auto-corrected: {_cmd_verb} -> {_corrected}"))
                result = await handle_slash(raw, session)
                if result is _EXIT_SENTINEL:
                    print(c(CYAN, "\n  Goodbye! 👋"))
                    break
                continue
            _write_text_cache(_last_input_path, raw)
            try:
                with turn_interrupt_handler():
                    session.run_turn(raw)
            except TurnInterrupted:
                removed, last_text = session.undo(1)
                session._autosave()
                _re_edit_default = last_text or raw
                _signal_state.submitted()
                if removed:
                    print(c(YELLOW, "  [interrupted] Turn rolled back; edit and press Enter to retry."))
                else:
                    print(c(YELLOW, "  [interrupted] Edit and press Enter to retry."))

        except KeyboardInterrupt:
            # Idle input state: Ctrl+C only arms the double-press exit flow.
            # Turn rollback is handled exclusively by the in-flight
            # TurnInterrupted branch around session.run_turn().
            if _signal_state.interrupt_requests_exit():
                await _terminal_notice("\n  Goodbye! 👋")
                break
            await _terminal_notice("\n  [confirm] Press Ctrl+C again within 5s to exit. Current input is unchanged.")
            continue
        except EOFError:
            # Ctrl+D exits immediately.
            print(c(CYAN, "\n  Goodbye! 👋"))
            break
        except Exception as _loop_exc:
            logger.error("Main loop error: {!r}", _loop_exc)
            print(c(RED, f"  ✗ Internal error; details were written to logs: {config.LOG_DIR}"))
            continue

    # Graceful shutdown: cancel all remaining asyncio tasks.
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    if _previous_sigtstp is not None:
        try:
            signal.signal(signal.SIGTSTP, _previous_sigtstp)
        except Exception:
            pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(c(CYAN, "\n\n  Goodbye! 👋"))
    except SystemExit:
        raise
    finally:
        detach_external_mcp_tools()


def run():
    """Synchronous entry point for the `pawn` CLI command (pip install)."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(c(CYAN, "\n\n  Goodbye! 👋"))
    except SystemExit:
        raise
    finally:
        detach_external_mcp_tools()
