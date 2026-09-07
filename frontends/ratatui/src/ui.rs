//! Ratatui UI for the PawnLogic headless client (Phase 2b M1).
//!
//! Alternate-screen full-terminal layout with a floating TOP status bar
//! (the Claude Code / Codex fullscreen model), an in-app scrolling history
//! pane, and a one-row composer. M1 renders read-only; the composer only
//! sends prompts and Esc interrupts.

use anyhow::Result;
use crossterm::event::{Event as CEvent, KeyCode, KeyEventKind, KeyModifiers, MouseEventKind};
use ratatui::{
    layout::{Constraint, Layout, Position},
    style::{Color, Modifier, Style},
    text::{Line, Span},
    widgets::{Block, Borders, Paragraph, Wrap},
    Frame,
};
use std::sync::{Arc, Mutex};

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
        if self.scroll_from_end > 0 {
            self.scroll_from_end = self.scroll_from_end.saturating_add(0);
        }
    }

    pub fn scroll_up(&mut self, rows: usize) {
        self.scroll_from_end = (self.scroll_from_end + rows).min(self.lines.len().saturating_sub(1));
    }

    pub fn scroll_down(&mut self, rows: usize) {
        self.scroll_from_end = self.scroll_from_end.saturating_sub(rows);
    }

    pub fn follow_tail(&mut self) {
        self.scroll_from_end = 0;
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
}

pub const STATUS_BAR_HEIGHT: u16 = 3;

pub fn draw(f: &mut Frame, state: &Arc<Mutex<UiState>>, composer: &str) {
    let state = state.lock().unwrap();
    let chunks = Layout::vertical([
        Constraint::Length(STATUS_BAR_HEIGHT),
        Constraint::Min(1),
        Constraint::Length(1),
    ])
    .split(f.area());

    // ── Floating TOP status bar (the Phase 2b signature) ──
    let elapsed = state
        .started_at
        .map(|t| t.elapsed().as_secs())
        .unwrap_or(0);
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
                Style::default().fg(Color::Black).bg(Color::Green).add_modifier(Modifier::BOLD),
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
    let total = state.history.lines.len();
    let height = chunks[1].height as usize;
    let end = total.saturating_sub(state.history.scroll_from_end);
    let start = end.saturating_sub(height);
    let visible: Vec<Line> = state.history.lines[start..end]
        .iter()
        .map(|l| Line::from(l.clone()))
        .collect();
    let history = Paragraph::new(visible)
        .wrap(Wrap { trim: false })
        .block(Block::default().borders(Borders::NONE));
    f.render_widget(history, chunks[1]);

    // ── Composer row ──
    let composer_text = format!("▶ {composer}");
    let composer_widget = Paragraph::new(Span::styled(
        composer_text.clone(),
        Style::default().add_modifier(Modifier::BOLD),
    ));
    f.render_widget(composer_widget, chunks[2]);

    // Cursor sits at the composer so typing feels native.
    let cursor_col = 2 + composer_width(&composer_text);
    f.set_cursor_position(Position::new(cursor_col.min(chunks[2].width - 1), chunks[2].y));
}

fn composer_width(composer: &str) -> u16 {
    u16::try_from(composer.chars().count()).unwrap_or(0)
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
                    state.history.push("── turn started ──".into());
                }
                "turn_completed" => {
                    state.running = false;
                    state.last_status = "completed".into();
                    state.history.push("── turn completed ──".into());
                }
                "turn_interrupted" | "turn_failed" => {
                    state.running = false;
                    state.last_status = stage.to_string();
                    state.history.push(format!("── turn {stage} ──"));
                }
                "interrupt_requested" => state.history.push("· Esc → interrupt sent".into()),
                "steer_accepted" => state.history.push("· steer accepted".into()),
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
                if !state.history.lines.last().is_some_and(|l| l.starts_with('│')) {
                    state.history.push("│ ".into());
                }
                state.history.append_to_last(text);
            }
            false
        }
        "result" => {
            state.running = false;
            state.last_status = "completed".into();
            let response = payload.get("response").and_then(|r| r.as_str()).unwrap_or("");
            state.history.push(format!("= {response:?}"));
            true
        }
        "error" => {
            let stage = payload.get("stage").and_then(|s| s.as_str()).unwrap_or("");
            let detail = payload.get("detail").and_then(|d| d.as_str()).unwrap_or("");
            state.history.push(format!("✗ [{stage}] {detail}"));
            false
        }
        "tool" => {
            let stage = payload.get("stage").and_then(|s| s.as_str()).unwrap_or("");
            let name = payload.get("tool_name").and_then(|n| n.as_str()).unwrap_or("");
            state.history.push(format!("· tool {stage}: {name}"));
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
pub fn handle_event(
    event: &CEvent,
    state: &Arc<Mutex<UiState>>,
) -> Option<&'static str> {
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
