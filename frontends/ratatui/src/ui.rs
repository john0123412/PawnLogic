//! Ratatui UI for the PawnLogic headless client (Phase 2b M1).
//!
//! Alternate-screen full-terminal layout with a floating TOP status bar
//! (the Claude Code / Codex fullscreen model), an in-app scrolling history
//! pane, and a one-row composer. M1 renders read-only; the composer only
//! sends prompts and Esc interrupts.

use crossterm::event::{Event as CEvent, KeyCode, KeyEventKind, KeyModifiers, MouseEventKind};
use ratatui::{
    layout::{Constraint, Layout, Position},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Wrap},
    Frame,
};
use std::sync::{Arc, Mutex};

use crate::composer::Composer;

/// Which line the history pane highlights while the user scrolls.
#[derive(Default)]
pub struct History {
    pub lines: Vec<String>,
    pub scroll_from_end: usize,
}

impl History {
    pub fn push(&mut self, line: String) {
        self.lines.push(line);
        if self.scroll_from_end > 0 {
            self.scroll_from_end += 1;
        }
    }

    pub fn append_to_last(&mut self, text: &str) {
        match self.lines.last_mut() {
            Some(last) => last.push_str(text),
            None => self.lines.push(text.to_string()),
        }
    }

    pub fn scroll_up(&mut self, rows: usize) {
        self.scroll_from_end = self.scroll_from_end.saturating_add(rows);
    }

    pub fn scroll_down(&mut self, rows: usize) {
        self.scroll_from_end = self.scroll_from_end.saturating_sub(rows);
    }
}

/// Shared UI state between the render loop and the wire callbacks.
#[derive(Default)]
pub struct UiState {
    pub history: History,
    /// Status bar: (model, phase_or_state, running: bool, elapsed: u64).
    pub model: String,
    pub running: bool,
    pub started_at: Option<std::time::Instant>,
    pub last_status: String,
    pub result_received: bool,
    pub command_received: bool,
    pub last_error: Option<String>,
    streamed_response: bool,
    /// Concatenation of every `stream` text this turn delivered, so a
    /// final `result` can append only the missing tail instead of the
    /// whole answer again.
    streamed_text: String,
}

pub const STATUS_BAR_HEIGHT: u16 = 3;

pub fn draw(f: &mut Frame, state: &Arc<Mutex<UiState>>, composer: &Composer) {
    let state = state.lock().unwrap();
    let chunks = Layout::vertical([
        Constraint::Length(STATUS_BAR_HEIGHT),
        Constraint::Min(1),
        Constraint::Length(1),
    ])
    .split(f.area());

    // ── Floating TOP status bar (the Phase 2b signature) ──
    let elapsed = state.started_at.map(|t| t.elapsed().as_secs()).unwrap_or(0);
    let state_text = if state.running {
        format!("⏱ {elapsed}s · streaming")
    } else if state.last_status.is_empty() {
        "idle".to_string()
    } else {
        state.last_status.clone()
    };
    let status = Paragraph::new(vec![
        Line::from(vec![
            Span::styled(
                " PawnLogic ",
                Style::default()
                    .fg(Color::Black)
                    .bg(Color::Green)
                    .add_modifier(Modifier::BOLD),
            ),
            Span::raw(" "),
            Span::styled(&state.model, Style::default().add_modifier(Modifier::BOLD)),
        ]),
        Line::from(Span::styled(state_text, Style::default().fg(Color::Cyan))),
        Line::from("─".repeat(chunks[0].width as usize)),
    ])
    .style(Style::default().bg(Color::DarkGray));
    f.render_widget(status, chunks[0]);

    // ── History pane with in-app scroll ──
    let all_lines: Vec<Line> = state
        .history
        .lines
        .iter()
        .map(|l| Line::from(l.clone()))
        .collect();
    let history = Paragraph::new(all_lines)
        .wrap(Wrap { trim: false })
        .block(Block::default().borders(Borders::NONE));
    let total_rows = wrapped_row_count(&state.history.lines, chunks[1].width);
    let max_scroll = total_rows.saturating_sub(chunks[1].height as usize);
    let from_end = state.history.scroll_from_end.min(max_scroll);
    let scroll_top = max_scroll.saturating_sub(from_end);
    let history = history.scroll((u16::try_from(scroll_top).unwrap_or(u16::MAX), 0));
    f.render_widget(history, chunks[1]);

    // ── Composer row ──
    let (visible_text, cursor_width) = composer_view(composer, chunks[2].width);
    let composer_text = format!("▶ {visible_text}");
    let composer_widget = Paragraph::new(Span::styled(
        composer_text.clone(),
        Style::default().add_modifier(Modifier::BOLD),
    ));
    f.render_widget(composer_widget, chunks[2]);

    // Cursor sits at the composer so typing feels native.
    if chunks[2].width > 0 {
        let cursor_col = 2_u16.saturating_add(cursor_width);
        f.set_cursor_position(Position::new(
            cursor_col.min(chunks[2].width.saturating_sub(1)),
            chunks[2].y,
        ));
    }
}

fn composer_view(composer: &Composer, terminal_width: u16) -> (&str, u16) {
    let text = composer.text();
    let cursor = composer.cursor();
    let budget = usize::from(terminal_width.saturating_sub(3));
    let mut start = 0;
    while Span::raw(&text[start..cursor]).width() > budget {
        let Some((offset, ch)) = text[start..cursor].char_indices().next() else {
            break;
        };
        start += offset + ch.len_utf8();
    }
    let width = Span::raw(&text[start..cursor]).width();
    (&text[start..], u16::try_from(width).unwrap_or(u16::MAX))
}

fn wrapped_row_count(lines: &[String], width: u16) -> usize {
    let width = usize::from(width.max(1));
    lines
        .iter()
        .flat_map(|line| line.split('\n'))
        .map(|line| Span::raw(line).width().max(1).div_ceil(width))
        .sum()
}

/// Append streamed answer text to the history transcript, opening the
/// `│ ` marker line on the first fragment and continuing it afterwards.
fn append_stream_text(state: &mut UiState, text: &str) {
    if !state
        .history
        .lines
        .last()
        .is_some_and(|l| l.starts_with('│'))
    {
        state.history.push("│ ".into());
    }
    state.history.append_to_last(text);
    state.streamed_text.push_str(text);
    state.streamed_response = true;
}

/// Map one wire event into history lines. Returns true when the event was
/// a `result` (the caller may finish a one-shot run).
pub fn apply_event(state: &Arc<Mutex<UiState>>, kind: &str, payload: &serde_json::Value) -> bool {
    let mut state = state.lock().unwrap();
    match kind {
        "status" => {
            let stage = payload.get("stage").and_then(|s| s.as_str()).unwrap_or("");
            match stage {
                "turn_started" => {
                    state.running = true;
                    state.started_at = Some(std::time::Instant::now());
                    state.result_received = false;
                    state.last_error = None;
                    state.streamed_response = false;
                    state.streamed_text.clear();
                    state.history.push("── turn started ──".into());
                }
                "turn_completed" => {
                    state.running = false;
                    state.last_status = "completed".into();
                    state.history.push("── turn completed ──".into());
                }
                "turn_interrupted" | "turn_cancelled" | "turn_failed" => {
                    state.running = false;
                    state.last_status = stage.to_string();
                    state.history.push(format!("── turn {stage} ──"));
                }
                "interrupt_requested" => state.history.push("· Esc → interrupt sent".into()),
                "steer_accepted" => {
                    state.last_status = "steer accepted — running next".into();
                    state.history.push("· steer accepted".into());
                }
                "ready" => {
                    state.model = payload
                        .get("model")
                        .and_then(|m| m.as_str())
                        .unwrap_or("unknown")
                        .to_string();
                    state.history.push("── ready ──".into());
                }
                _ => {}
            }
            false
        }
        "stream" => {
            if let Some(text) = payload.get("text").and_then(|t| t.as_str()) {
                append_stream_text(&mut state, text);
            }
            false
        }
        "result" => {
            state.running = false;
            state.last_status = "completed".into();
            state.result_received = true;
            let response = payload
                .get("response")
                .and_then(|r| r.as_str())
                .unwrap_or("");
            // A backend that already streamed the full answer carries the
            // complete text in `result`; append only a genuinely missing
            // tail (older backends hold back a trailing `<...` fragment
            // in the renderer and never stream it). Appending the whole
            // response again would duplicate every streamed answer.
            if !response.is_empty() {
                let streamed_so_far = state.streamed_text.clone();
                if let Some(tail) = response.strip_prefix(streamed_so_far.as_str()) {
                    if !tail.is_empty() {
                        append_stream_text(&mut state, tail);
                    }
                } else {
                    // No stream arrived (or it diverged): show the result.
                    state.history.push(format!("│ {response}"));
                }
            }
            state.streamed_response = false;
            true
        }
        "error" => {
            let stage = payload.get("stage").and_then(|s| s.as_str()).unwrap_or("");
            let detail = payload.get("detail").and_then(|d| d.as_str()).unwrap_or("");
            state.last_error = Some(format!("[{stage}] {detail}"));
            state.history.push(format!("✗ [{stage}] {detail}"));
            false
        }
        "tool" => {
            let stage = payload.get("stage").and_then(|s| s.as_str()).unwrap_or("");
            let name = payload
                .get("tool_name")
                .and_then(|n| n.as_str())
                .unwrap_or("");
            state.history.push(format!("· tool {stage}: {name}"));
            false
        }
        "command_result" => {
            state.command_received = true;
            let verb = payload.get("verb").and_then(|v| v.as_str()).unwrap_or("");
            let output = payload
                .get("output")
                .and_then(|o| o.as_array())
                .cloned()
                .unwrap_or_default();
            state.history.push(format!("── {verb} ──"));
            for row in output {
                if let Some(text) = row.as_str() {
                    state.history.push(text.to_string());
                }
            }
            false
        }
        _ => false,
    }
}

/// Convert a crossterm key event into an optional semantic action name.
pub fn key_action(key: &crossterm::event::KeyEvent) -> Option<&'static str> {
    if key.kind != KeyEventKind::Press {
        return None;
    }
    match key.code {
        KeyCode::Esc => Some("interrupt"),
        KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => Some("quit"),
        _ => None,
    }
}

/// Consume one crossterm event, mutating history scroll or reporting actions.
pub fn handle_event(event: &CEvent, state: &Arc<Mutex<UiState>>) -> Option<&'static str> {
    match event {
        CEvent::Key(key) => {
            if let Some(action) = key_action(key) {
                return Some(action);
            }
            if key.kind == KeyEventKind::Press {
                match key.code {
                    KeyCode::Up => state.lock().unwrap().history.scroll_up(1),
                    KeyCode::Down => state.lock().unwrap().history.scroll_down(1),
                    KeyCode::PageUp => state.lock().unwrap().history.scroll_up(10),
                    KeyCode::PageDown => state.lock().unwrap().history.scroll_down(10),
                    _ => {}
                }
            }
            None
        }
        CEvent::Mouse(mouse) => match mouse.kind {
            MouseEventKind::ScrollUp => {
                state.lock().unwrap().history.scroll_up(3);
                None
            }
            MouseEventKind::ScrollDown => {
                state.lock().unwrap().history.scroll_down(3);
                None
            }
            _ => None,
        },
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn history_scroll_uses_visual_row_offsets() {
        let mut history = History::default();
        history.push("one logical line can wrap across many visual rows".into());
        history.scroll_up(10);
        assert_eq!(history.scroll_from_end, 10);
        history.scroll_down(3);
        assert_eq!(history.scroll_from_end, 7);
    }

    #[test]
    fn wrapped_history_counts_terminal_rows() {
        let lines = vec!["123456".to_string(), String::new()];
        assert_eq!(wrapped_row_count(&lines, 3), 3);
    }

    #[test]
    fn command_result_lands_in_history() {
        let state = Arc::new(Mutex::new(UiState::default()));
        apply_event(
            &state,
            "command_result",
            &json!({"verb": "/keys", "output": ["DEEPSEEK_API_KEY: true"]}),
        );
        let history = state.lock().unwrap().history.lines.clone();
        assert!(history.iter().any(|l| l.contains("── /keys ──")));
        assert!(history.iter().any(|l| l.contains("DEEPSEEK_API_KEY: true")));
    }

    #[test]
    fn steer_accepted_surfaces_in_status_text() {
        let state = Arc::new(Mutex::new(UiState::default()));
        apply_event(&state, "status", &json!({"stage": "steer_accepted"}));
        let state = state.lock().unwrap();
        assert_eq!(state.last_status, "steer accepted — running next");
    }

    #[test]
    fn tool_events_render_start_and_result() {
        let state = Arc::new(Mutex::new(UiState::default()));
        apply_event(
            &state,
            "tool",
            &json!({"stage": "started", "tool_name": "list_dir", "iteration": 0}),
        );
        apply_event(
            &state,
            "tool",
            &json!({"stage": "result", "tool_name": "list_dir", "iteration": 0, "status": "success"}),
        );
        let history = state.lock().unwrap().history.lines.clone();
        assert!(history.iter().any(|l| l.contains("tool started: list_dir")));
        assert!(history.iter().any(|l| l.contains("tool result: list_dir")));
    }

    #[test]
    fn final_result_does_not_duplicate_streamed_response() {
        let state = Arc::new(Mutex::new(UiState::default()));
        apply_event(&state, "stream", &json!({"text": "unique-answer"}));
        apply_event(
            &state,
            "result",
            &json!({"response": "unique-answer", "model": "test"}),
        );

        let rendered = state.lock().unwrap().history.lines.join("\n");
        assert_eq!(rendered.matches("unique-answer").count(), 1, "{rendered}");
    }

    #[test]
    fn final_result_renders_when_no_stream_was_received() {
        let state = Arc::new(Mutex::new(UiState::default()));
        apply_event(
            &state,
            "result",
            &json!({"response": "fallback-answer", "model": "test"}),
        );

        let rendered = state.lock().unwrap().history.lines.join("\n");
        assert_eq!(rendered.matches("fallback-answer").count(), 1, "{rendered}");
    }

    #[test]
    fn composer_cursor_uses_terminal_cell_width() {
        let mut composer = Composer::default();
        composer.insert_str("a\u{4e2d}🙂");
        let (_, cursor_width) = composer_view(&composer, 80);
        assert_eq!(cursor_width, 5);
    }

    #[test]
    fn cancelled_turn_leaves_the_running_state() {
        let state = Arc::new(Mutex::new(UiState::default()));
        apply_event(&state, "status", &json!({"stage": "turn_started"}));
        apply_event(&state, "status", &json!({"stage": "turn_cancelled"}));

        let state = state.lock().unwrap();
        assert!(!state.running);
        assert_eq!(state.last_status, "turn_cancelled");
    }

    #[test]
    fn result_appends_only_the_tail_of_a_partially_streamed_answer() {
        // Wire path observed against the 0.3.10 backend: the renderer
        // held back a trailing `<3` fragment, so only `a ` streamed and
        // the final `result` still carried the whole answer. The client
        // must append the missing tail, not duplicate the prefix.
        let state = Arc::new(Mutex::new(UiState::default()));
        apply_event(&state, "status", &json!({"stage": "turn_started"}));
        apply_event(&state, "stream", &json!({"text": "a "}));
        apply_event(&state, "result", &json!({"response": "a <3"}));

        let s = state.lock().unwrap();
        let rendered: Vec<String> = s.history.lines.clone();
        let joined = rendered.join("\n");
        assert!(
            joined.contains("│ a <3"),
            "streamed answer tail missing: {rendered:?}"
        );
        assert!(
            !joined.matches("a ").count() > 1 || joined.matches("a <3").count() == 1,
            "streamed prefix duplicated: {rendered:?}"
        );
    }

    #[test]
    fn fully_streamed_answer_is_not_duplicated_by_the_result() {
        let state = Arc::new(Mutex::new(UiState::default()));
        apply_event(&state, "status", &json!({"stage": "turn_started"}));
        apply_event(&state, "stream", &json!({"text": "hello world"}));
        apply_event(&state, "result", &json!({"response": "hello world"}));

        let s = state.lock().unwrap();
        let joined = s.history.lines.join("\n");
        assert_eq!(
            joined.matches("hello world").count(),
            1,
            "fully streamed answer duplicated: {joined:?}"
        );
    }

    #[test]
    fn unstreamed_answer_is_rendered_from_the_result() {
        let state = Arc::new(Mutex::new(UiState::default()));
        apply_event(&state, "status", &json!({"stage": "turn_started"}));
        apply_event(&state, "result", &json!({"response": "no stream backend"}));

        let s = state.lock().unwrap();
        assert!(s.history.lines.join("\n").contains("│ no stream backend"));
    }

    #[test]
    fn multiline_stream_draws_each_line() {
        use ratatui::backend::TestBackend;
        use ratatui::Terminal;
        let state = Arc::new(Mutex::new(UiState::default()));
        {
            let mut s = state.lock().unwrap();
            s.history.push("│ line one".into());
            s.history.append_to_last("\nline two\nline three");
        }
        let composer = Composer::default();
        let mut terminal = Terminal::new(TestBackend::new(40, 12)).unwrap();
        terminal.draw(|f| draw(f, &state, &composer)).unwrap();
        let buffer = terminal.backend().buffer().clone();
        let flat: String = buffer
            .content()
            .iter()
            .map(|cell| cell.symbol().to_string())
            .collect::<String>()
            .replace(' ', "");
        assert!(
            flat.contains("lineone") && flat.contains("linetwo") && flat.contains("linethree"),
            "multi-line stream lost its newlines on screen: {flat:?}"
        );
    }
}
