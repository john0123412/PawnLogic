//! PawnLogic Ratatui frontend — Phase 2b M1.
//!
//! Fullscreen alternate-screen client for `pawn serve`: floating TOP
//! status bar, in-app scrolling history pane, one-row composer. Enter
//! sends a prompt (or a steer while a Turn runs), Esc interrupts,
//! Ctrl+C quits. `--once <text>` runs a single prompt headless and dumps
//! the final screen for acceptance tests.

mod composer;
mod ui;
mod wire;

use anyhow::{bail, Context, Result};
use clap::Parser;
use crossterm::{
    cursor::{Hide, Show},
    event::{
        DisableBracketedPaste, DisableMouseCapture, EnableBracketedPaste, EnableMouseCapture,
        Event as CEvent, KeyCode, KeyModifiers,
    },
    terminal::{EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{backend::CrosstermBackend, Terminal};
use std::collections::VecDeque;
use std::io::Stdout;
use std::path::PathBuf;
use std::sync::{mpsc, Arc, Mutex};
use std::time::Duration;

use composer::Composer;
use ui::{apply_event, handle_event, UiState};
use wire::parse_line;

const STDERR_TAIL_LINES: usize = 20;

#[derive(Debug)]
enum BackendSignal {
    Closed,
    ReadError(String),
    ProtocolError(String),
}

struct TerminalModeGuard;

impl TerminalModeGuard {
    fn enter() -> Result<Self> {
        crossterm::terminal::enable_raw_mode().context("failed to enable terminal raw mode")?;
        if let Err(error) = crossterm::execute!(
            std::io::stdout(),
            EnterAlternateScreen,
            EnableMouseCapture,
            EnableBracketedPaste,
            Hide
        ) {
            let _ = crossterm::terminal::disable_raw_mode();
            return Err(error).context("failed to enter terminal UI mode");
        }
        Ok(Self)
    }
}

impl Drop for TerminalModeGuard {
    fn drop(&mut self) {
        let _ = crossterm::execute!(
            std::io::stdout(),
            Show,
            DisableBracketedPaste,
            DisableMouseCapture,
            LeaveAlternateScreen
        );
        let _ = crossterm::terminal::disable_raw_mode();
    }
}

#[derive(Parser, Debug)]
#[command(
    name = "pawnlogic-tui",
    about = "RatatuI frontend for pawn serve (wire v1, ADR 0011)",
    version
)]
struct Args {
    /// Model alias to start the server with.
    #[arg(long, default_value = "ds-v4-flash")]
    model: String,
    /// Non-interactive acceptance mode: run one prompt, dump the screen, exit.
    #[arg(long)]
    once: Option<String>,
    /// Non-interactive acceptance mode: run one slash command, dump the screen, exit.
    #[arg(long)]
    once_command: Option<String>,
    /// Where to write the final rendered screen (acceptance harness).
    #[arg(long)]
    dump: Option<PathBuf>,
    /// Extra environment for the spawned server (KEY=value, repeatable).
    #[arg(long = "env")]
    envs: Vec<String>,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let mut server_env: Vec<(String, String)> = Vec::new();
    for item in &args.envs {
        if let Some((key, value)) = item.split_once('=') {
            server_env.push((key.to_string(), value.to_string()));
        }
    }

    if let Some(command) = args.once_command {
        return run_once_command(&args.model, &command, args.dump.as_deref(), &server_env);
    }
    if let Some(prompt) = args.once {
        return run_once(&args.model, &prompt, args.dump.as_deref(), &server_env);
    }
    run_interactive(&args.model, &server_env)
}

fn spawn_server(model: &str, extra_env: &[(String, String)]) -> Result<std::process::Child> {
    let server = std::env::var("PAWNLOGIC_TUI_SERVER").ok();
    let (program, args) = server_command_parts(server.as_deref());
    let mut cmd = std::process::Command::new(program);
    cmd.args(args)
        .arg("--model")
        .arg(model)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    for (key, value) in extra_env {
        cmd.env(key, value);
    }
    cmd.spawn().context("failed to spawn `pawn serve`")
}

fn server_command_parts(server_override: Option<&str>) -> (String, Vec<String>) {
    let server = server_override
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("python3 -m pawnlogic serve");
    let mut parts = server.split_whitespace();
    let program = parts.next().unwrap_or("python3").to_string();
    let args: Vec<String> = parts.map(str::to_string).collect();
    (program, args)
}

fn interactive_command_guidance(line: &str) -> Option<&'static str> {
    let mut parts = line.split_whitespace();
    match (parts.next(), parts.next()) {
        (Some("/model"), None) => Some(
            "The model selector is not available over wire v1. Use /model <alias> or the Python REPL.",
        ),
        (Some("/provider"), None) => Some(
            "The provider panel is not available over wire v1. Use /provider list or the Python REPL.",
        ),
        (Some("/skills"), None) => Some(
            "The skills panel is not available over wire v1. Use a text subcommand or the Python REPL.",
        ),
        (Some("/setkey"), _) => Some(
            "The key wizard is not available over wire v1. Configure keys in the Python REPL.",
        ),
        _ => None,
    }
}

fn spawn_event_reader(
    stdout: std::process::ChildStdout,
    state: Arc<Mutex<UiState>>,
) -> (std::thread::JoinHandle<()>, mpsc::Receiver<BackendSignal>) {
    let (sender, receiver) = mpsc::channel();
    let reader = std::thread::spawn(move || {
        use std::io::BufRead;

        for line in std::io::BufReader::new(stdout).lines() {
            match line {
                Ok(line) => match parse_line(&line) {
                    Ok(Some(event)) => {
                        apply_event(&state, &event.kind, &event.payload);
                    }
                    Ok(None) => {}
                    Err(error) => {
                        let _ = sender.send(BackendSignal::ProtocolError(error.to_string()));
                        return;
                    }
                },
                Err(error) => {
                    let _ = sender.send(BackendSignal::ReadError(error.to_string()));
                    return;
                }
            }
        }
        let _ = sender.send(BackendSignal::Closed);
    });
    (reader, receiver)
}

fn spawn_stderr_reader(
    stderr: std::process::ChildStderr,
) -> (Arc<Mutex<VecDeque<String>>>, std::thread::JoinHandle<()>) {
    let tail = Arc::new(Mutex::new(VecDeque::new()));
    let reader_tail = Arc::clone(&tail);
    let reader = std::thread::spawn(move || {
        use std::io::BufRead;

        for line in std::io::BufReader::new(stderr)
            .lines()
            .map_while(Result::ok)
        {
            let mut tail = reader_tail.lock().unwrap();
            tail.push_back(line);
            while tail.len() > STDERR_TAIL_LINES {
                tail.pop_front();
            }
        }
    });
    (tail, reader)
}

fn backend_signal_error(
    signal: BackendSignal,
    stderr_tail: &Arc<Mutex<VecDeque<String>>>,
) -> anyhow::Error {
    let reason = match signal {
        BackendSignal::Closed => "backend exited unexpectedly".to_string(),
        BackendSignal::ReadError(detail) => format!("backend output read failed: {detail}"),
        BackendSignal::ProtocolError(detail) => format!("backend protocol error: {detail}"),
    };
    let stderr = stderr_tail
        .lock()
        .unwrap()
        .iter()
        .cloned()
        .collect::<Vec<_>>()
        .join("\n");
    if stderr.is_empty() {
        anyhow::anyhow!(reason)
    } else {
        anyhow::anyhow!("{reason}\nbackend stderr:\n{stderr}")
    }
}

fn check_backend(
    receiver: &mpsc::Receiver<BackendSignal>,
    stderr_tail: &Arc<Mutex<VecDeque<String>>>,
) -> Result<()> {
    match receiver.try_recv() {
        Ok(signal) => Err(backend_signal_error(signal, stderr_tail)),
        Err(mpsc::TryRecvError::Empty) => Ok(()),
        Err(mpsc::TryRecvError::Disconnected) => bail!("backend monitor stopped unexpectedly"),
    }
}

/// One slash command, render the command_result, dump the screen, exit.
fn run_once_command(
    model: &str,
    command: &str,
    dump: Option<&std::path::Path>,
    extra_env: &[(String, String)],
) -> Result<()> {
    if let Some(guidance) = interactive_command_guidance(command) {
        bail!(guidance);
    }
    let mut child = spawn_server(model, extra_env)?;
    let mut stdin = child.stdin.take().context("server stdin")?;
    let stdout = child.stdout.take().context("server stdout")?;
    let stderr = child.stderr.take().context("server stderr")?;
    let state = Arc::new(Mutex::new(UiState::default()));
    let (reader, backend_receiver) = spawn_event_reader(stdout, Arc::clone(&state));
    let (stderr_tail, stderr_reader) = spawn_stderr_reader(stderr);

    use std::io::Write;
    writeln!(stdin, "{}", wire::build_request("command", command, false))?;

    let deadline = std::time::Instant::now() + Duration::from_secs(60);
    let mut outcome = loop {
        if let Err(error) = check_backend(&backend_receiver, &stderr_tail) {
            break Err(error);
        }
        let state = state.lock().unwrap();
        if let Some(error) = &state.last_error {
            break Err(anyhow::anyhow!("command failed: {error}"));
        }
        if state.command_received {
            break Ok(());
        }
        drop(state);
        if std::time::Instant::now() > deadline {
            break Err(anyhow::anyhow!(
                "acceptance timeout: command_result did not arrive in 60s"
            ));
        }
        std::thread::sleep(Duration::from_millis(50));
    };
    if outcome.is_ok() {
        if let Err(error) = writeln!(stdin, "{}", wire::build_request("shutdown", "", false)) {
            outcome = Err(error.into());
        }
    }
    if outcome.is_err() {
        let _ = child.kill();
    }
    let _ = child.wait();
    reader.join().ok();
    stderr_reader.join().ok();
    outcome?;

    if let Some(path) = dump {
        let state = state.lock().unwrap();
        std::fs::write(
            path,
            format!(
                "model: {}\n---\n{}",
                state.model,
                state.history.lines.join("\n")
            ),
        )?;
        println!("screen dumped to {}", path.display());
    }
    println!("ACCEPTANCE OK");
    Ok(())
}

/// One prompt, render until the result arrives, dump the screen, exit.
fn run_once(
    model: &str,
    prompt: &str,
    dump: Option<&std::path::Path>,
    extra_env: &[(String, String)],
) -> Result<()> {
    let mut child = spawn_server(model, extra_env)?;
    let mut stdin = child.stdin.take().context("server stdin")?;
    let stdout = child.stdout.take().context("server stdout")?;
    let stderr = child.stderr.take().context("server stderr")?;
    let state = Arc::new(Mutex::new(UiState::default()));
    let (reader, backend_receiver) = spawn_event_reader(stdout, Arc::clone(&state));
    let (stderr_tail, stderr_reader) = spawn_stderr_reader(stderr);

    use std::io::Write;
    writeln!(stdin, "{}", wire::build_request("prompt", prompt, false))?;

    // Wait until the result event renders (reader thread updates state).
    let deadline = std::time::Instant::now() + Duration::from_secs(120);
    let mut outcome = loop {
        if let Err(error) = check_backend(&backend_receiver, &stderr_tail) {
            break Err(error);
        }
        let state = state.lock().unwrap();
        if let Some(error) = &state.last_error {
            break Err(anyhow::anyhow!("turn failed: {error}"));
        }
        if state.result_received {
            break Ok(());
        }
        drop(state);
        if std::time::Instant::now() > deadline {
            break Err(anyhow::anyhow!(
                "acceptance timeout: turn did not complete in 120s"
            ));
        }
        std::thread::sleep(Duration::from_millis(50));
    };
    if outcome.is_ok() {
        std::thread::sleep(Duration::from_millis(200));
        if let Err(error) = writeln!(stdin, "{}", wire::build_request("shutdown", "", false)) {
            outcome = Err(error.into());
        }
    }
    if outcome.is_err() {
        let _ = child.kill();
    }
    let _ = child.wait();
    reader.join().ok();
    stderr_reader.join().ok();
    outcome?;

    if let Some(path) = dump {
        let state = state.lock().unwrap();
        std::fs::write(
            path,
            format!(
                "model: {}\nlast_status: {}\n---\n{}",
                state.model,
                state.last_status,
                state.history.lines.join("\n")
            ),
        )?;
        println!("screen dumped to {}", path.display());
    }
    println!("ACCEPTANCE OK");
    Ok(())
}

/// Interactive fullscreen loop (M1: prompts, steer, interrupt; commands land in M2).
fn run_interactive(model: &str, extra_env: &[(String, String)]) -> Result<()> {
    let mut child = spawn_server(model, extra_env)?;
    let mut stdin = child.stdin.take().context("server stdin")?;
    let stdout = child.stdout.take().context("server stdout")?;
    let stderr = child.stderr.take().context("server stderr")?;
    let state = Arc::new(Mutex::new(UiState::default()));
    let (reader, backend_receiver) = spawn_event_reader(stdout, Arc::clone(&state));
    let (stderr_tail, stderr_reader) = spawn_stderr_reader(stderr);

    let _terminal_mode = TerminalModeGuard::enter()?;
    let terminal = Terminal::new(CrosstermBackend::new(std::io::stdout()))?;
    let terminal = Arc::new(Mutex::new(terminal));
    let mut composer = Composer::default();

    // A synchronous poll loop, not an async event stream: the loop redraws
    // every tick so server-driven state changes (ready, turn lifecycle,
    // streamed text) appear without waiting for a keypress.
    let result = drive_loop(
        &state,
        &terminal,
        &mut composer,
        &mut stdin,
        &backend_receiver,
        &stderr_tail,
    );

    for _ in 0..20 {
        if child.try_wait()?.is_some() {
            break;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    if child.try_wait()?.is_none() {
        let _ = child.kill();
    }
    let _ = child.wait();
    reader.join().ok();
    stderr_reader.join().ok();
    result
}

fn drive_loop(
    state: &Arc<Mutex<UiState>>,
    terminal: &Arc<Mutex<Terminal<CrosstermBackend<Stdout>>>>,
    composer: &mut Composer,
    stdin: &mut std::process::ChildStdin,
    backend_receiver: &mpsc::Receiver<BackendSignal>,
    stderr_tail: &Arc<Mutex<VecDeque<String>>>,
) -> Result<()> {
    use std::io::Write;
    loop {
        check_backend(backend_receiver, stderr_tail)?;
        {
            let mut t = terminal.lock().unwrap();
            t.draw(|frame| ui::draw(frame, state, composer))?;
        }
        // Redraw every tick; poll waits up to 200ms for the next input.
        if crossterm::event::poll(Duration::from_millis(200))? {
            let event = crossterm::event::read()?;
            // handle_event owns Esc/Ctrl+C actions, arrow/page scrolling,
            // and mouse-wheel scrolling; it reports semantic actions.
            if let Some(action) = handle_event(&event, state) {
                match action {
                    "interrupt" => {
                        let running = state.lock().unwrap().running;
                        if running {
                            writeln!(stdin, "{}", wire::build_request("interrupt", "", false))?;
                        }
                    }
                    "quit" => {
                        writeln!(stdin, "{}", wire::build_request("shutdown", "", false))?;
                        return Ok(());
                    }
                    _ => {}
                }
                continue;
            }
            if let CEvent::Key(key) = &event {
                if key.kind == crossterm::event::KeyEventKind::Press {
                    match key.code {
                        KeyCode::Enter => {
                            let text = composer.text().trim().to_string();
                            if matches!(text.as_str(), "/q" | "/quit" | "/exit") {
                                writeln!(stdin, "{}", wire::build_request("shutdown", "", false))?;
                                return Ok(());
                            }
                            if !text.is_empty() {
                                if text.starts_with('/') {
                                    if let Some(guidance) = interactive_command_guidance(&text) {
                                        state.lock().unwrap().history.push(format!("✗ {guidance}"));
                                        composer.clear();
                                        continue;
                                    }
                                    // M2: slash commands ride the command request;
                                    // the core dispatches and answers command_result.
                                    writeln!(
                                        stdin,
                                        "{}",
                                        wire::build_request("command", &text, false)
                                    )?;
                                } else {
                                    let running = state.lock().unwrap().running;
                                    writeln!(
                                        stdin,
                                        "{}",
                                        wire::build_request("prompt", &text, running)
                                    )?;
                                }
                                composer.clear();
                            }
                        }
                        KeyCode::Backspace => {
                            composer.backspace();
                        }
                        KeyCode::Delete => composer.delete(),
                        KeyCode::Left => composer.move_left(),
                        KeyCode::Right => composer.move_right(),
                        KeyCode::Home => composer.move_home(),
                        KeyCode::End => composer.move_end(),
                        KeyCode::Tab => composer.insert_str("    "),
                        KeyCode::Char('a') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                            composer.move_home();
                        }
                        KeyCode::Char('e') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                            composer.move_end();
                        }
                        KeyCode::Char('u') if key.modifiers.contains(KeyModifiers::CONTROL) => {
                            composer.clear();
                        }
                        KeyCode::Char(ch)
                            if !key
                                .modifiers
                                .intersects(KeyModifiers::CONTROL | KeyModifiers::SUPER) =>
                        {
                            composer.insert_char(ch);
                        }
                        _ => {}
                    }
                }
            }
            if let CEvent::Paste(text) = &event {
                composer.insert_str(text);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::VecDeque;
    use std::sync::{mpsc, Arc, Mutex};

    use super::{check_backend, interactive_command_guidance, server_command_parts, BackendSignal};

    #[test]
    fn server_override_is_a_complete_backend_command() {
        let (program, args) = server_command_parts(Some("/opt/pawn/bin/python -m pawnlogic serve"));
        assert_eq!(program, "/opt/pawn/bin/python");
        assert_eq!(args, ["-m", "pawnlogic", "serve"]);
    }

    #[test]
    fn default_server_command_uses_python3_serve() {
        let (program, args) = server_command_parts(None);
        assert_eq!(program, "python3");
        assert_eq!(args, ["-m", "pawnlogic", "serve"]);
    }

    #[test]
    fn backend_disconnect_includes_captured_stderr() {
        let (sender, receiver) = mpsc::channel();
        sender.send(BackendSignal::Closed).unwrap();
        let stderr = Arc::new(Mutex::new(VecDeque::from(["backend detail".into()])));

        let error = check_backend(&receiver, &stderr).unwrap_err();
        let detail = error.to_string();
        assert!(detail.contains("backend exited unexpectedly"));
        assert!(detail.contains("backend detail"));
    }

    #[test]
    fn interactive_wire_commands_fail_fast_with_text_alternatives() {
        assert!(interactive_command_guidance("/model")
            .unwrap()
            .contains("/model <alias>"));
        assert!(interactive_command_guidance("/provider")
            .unwrap()
            .contains("/provider list"));
        assert!(interactive_command_guidance("/skills").is_some());
        assert!(interactive_command_guidance("/setkey").is_some());
        assert!(interactive_command_guidance("/model ds-v4-flash").is_none());
        assert!(interactive_command_guidance("/provider list").is_none());
    }
}
