//! PawnLogic Ratatui frontend — Phase 2b M1.
//!
//! Fullscreen alternate-screen client for `pawn serve`: floating TOP
//! status bar, in-app scrolling history pane, one-row composer. Enter
//! sends a prompt (or a steer while a Turn runs), Esc interrupts,
//! Ctrl+C quits. `--once <text>` runs a single prompt headless and dumps
//! the final screen for acceptance tests.

mod ui;
mod wire;

use anyhow::{bail, Context, Result};
use clap::Parser;
use std::path::PathBuf;
use crossterm::event::{Event as CEvent, EventStream, KeyCode, KeyEventKind};
use futures::StreamExt;
use ratatui::{backend::CrosstermBackend, Terminal};
use std::io::Stdout;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use ui::{apply_event, handle_event, key_action, UiState};
use wire::{parse_line, Event};

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
        return run_once_command(
            &args.model,
            &command,
            args.dump.as_deref(),
            &server_env,
        );
    }
    if let Some(prompt) = args.once {
        return run_once(&args.model, &prompt, args.dump.as_deref(), &server_env);
    }
    run_interactive(&args.model, &server_env)
}

fn spawn_server(model: &str, extra_env: &[(String, String)]) -> Result<std::process::Child> {
    let mut cmd = std::process::Command::new("python");
    cmd.arg("-m")
        .arg("pawnlogic")
        .arg("serve")
        .arg("--model")
        .arg(model)
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null());
    for (key, value) in extra_env {
        cmd.env(key, value);
    }
    cmd.spawn().context("failed to spawn `pawn serve`")
}

/// One slash command, render the command_result, dump the screen, exit.
fn run_once_command(
    model: &str,
    command: &str,
    dump: Option<&std::path::Path>,
    extra_env: &[(String, String)],
) -> Result<()> {
    let mut child = spawn_server(model, extra_env)?;
    let mut stdin = child.stdin.take().context("server stdin")?;
    let stdout = child.stdout.take().context("server stdout")?;
    let state = Arc::new(Mutex::new(UiState::default()));
    let reader_state = Arc::clone(&state);
    let reader = std::thread::spawn(move || {
        use std::io::BufRead;
        for line in std::io::BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(event) = parse_line(&line) {
                apply_event(&reader_state, &event.kind, &event.payload);
            }
        }
    });

    use std::io::Write;
    writeln!(stdin, "{}", wire::build_request("command", command, false))?;

    let deadline = std::time::Instant::now() + Duration::from_secs(60);
    loop {
        let state = state.lock().unwrap();
        let rendered = state
            .history
            .lines
            .iter()
            .any(|l| l.contains(&format!("── {command} ──")));
        drop(state);
        if rendered {
            break;
        }
        if std::time::Instant::now() > deadline {
            bail!("acceptance timeout: command_result did not arrive in 60s");
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    writeln!(stdin, "{}", wire::build_request("shutdown", "", false))?;
    let _ = child.wait();
    reader.join().ok();

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
    let state = Arc::new(Mutex::new(UiState::default()));
    let reader_state = Arc::clone(&state);
    let reader = std::thread::spawn(move || {
        use std::io::BufRead;
        for line in std::io::BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(event) = parse_line(&line) {
                apply_event(&reader_state, &event.kind, &event.payload);
            }
        }
    });

    use std::io::Write;
    writeln!(stdin, "{}", wire::build_request("prompt", prompt, false))?;

    // Wait until the result event renders (reader thread updates state).
    let deadline = std::time::Instant::now() + Duration::from_secs(120);
    loop {
        if state.lock().unwrap().last_status == "completed" {
            break;
        }
        if std::time::Instant::now() > deadline {
            bail!("acceptance timeout: turn did not complete in 120s");
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    std::thread::sleep(Duration::from_millis(200)); // let trailing streams land
    writeln!(stdin, "{}", wire::build_request("shutdown", "", false))?;
    let _ = child.wait();
    reader.join().ok();

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
    let state = Arc::new(Mutex::new(UiState::default()));
    let reader_state = Arc::clone(&state);
    let reader = std::thread::spawn(move || {
        use std::io::BufRead;
        for line in std::io::BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(event) = parse_line(&line) {
                apply_event(&reader_state, &event.kind, &event.payload);
            }
        }
    });

    let terminal = Terminal::new(CrosstermBackend::new(std::io::stdout()))?;
    let terminal = Arc::new(Mutex::new(terminal));
    let mut composer = String::new();

    crossterm::terminal::enable_raw_mode()?;
    crossterm::execute!(std::io::stdout(), crossterm::terminal::EnterAlternateScreen)?;

    let mut events = EventStream::new();
    let result = futures::executor::block_on(drive_loop(
        &mut events, &state, &terminal, &mut composer, &mut stdin,
    ));

    crossterm::execute!(std::io::stdout(), crossterm::terminal::LeaveAlternateScreen)?;
    crossterm::terminal::disable_raw_mode()?;
    let _ = child.kill();
    reader.join().ok();
    result
}

async fn drive_loop(
    events: &mut EventStream,
    state: &Arc<Mutex<UiState>>,
    terminal: &Arc<Mutex<Terminal<CrosstermBackend<Stdout>>>>,
    composer: &mut String,
    stdin: &mut std::process::ChildStdin,
) -> Result<()> {
    use std::io::Write;
    loop {
        {
            let mut t = terminal.lock().unwrap();
            t.draw(|frame| ui::draw(frame, state, composer))?;
        }
        if let Some(Ok(CEvent::Key(key))) = events.next().await {
            if key.kind == KeyEventKind::Press {
                if let Some(action) = key_action(&key) {
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
                match key.code {
                    KeyCode::Char(ch) => composer.push(ch),
                    KeyCode::Backspace => {
                        composer.pop();
                    }
                    KeyCode::Enter => {
                        let running = state.lock().unwrap().running;
                        if running {
                            writeln!(stdin, "{}", wire::build_request("interrupt", "", false))?;
                        }
                    }
                    KeyCode::Char('c') if key.modifiers.contains(crossterm::event::KeyModifiers::CONTROL) => {
                        writeln!(stdin, "{}", wire::build_request("shutdown", "", false))?;
                        return Ok(());
                    }
                    KeyCode::Enter => {
                        let text = composer.trim().to_string();
                        composer.clear();
                        if text == "/quit" {
                            writeln!(stdin, "{}", wire::build_request("shutdown", "", false))?;
                            return Ok(());
                        }
                        if !text.is_empty() {
                            if text.starts_with('/') {
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
                        }
                    }
                    _ => {}
                }
            }
        }
    }
}
