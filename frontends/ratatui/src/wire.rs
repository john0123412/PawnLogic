//! Wire parsing for the PawnLogic headless serve protocol (ADR 0011, v1).
//!
//! The Python contract suite (tests/test_headless_contract.py) and the
//! golden fixture tests/fixtures/serve_events_v1.jsonl are the protocol
//! freeze; this module must accept every shape in that fixture and reject
//! unknown versions so a protocol drift fails loudly in CI.

use anyhow::{bail, Context, Result};
use serde_json::Value;

/// Every event type the v1 wire defines (requests and events).
pub const KNOWN_V1_EVENT_TYPES: [&str; 7] = [
    "status",
    "stream",
    "tool",
    "result",
    "error",
    "command_result",
    "prompt",
];

/// One parsed wire message.
#[derive(Debug, Clone, PartialEq)]
pub struct Event {
    pub version: u64,
    pub kind: String,
    pub payload: Value,
}

impl Event {
    pub fn stage(&self) -> Option<&str> {
        self.payload.get("stage").and_then(|s| s.as_str())
    }

    pub fn text(&self) -> Option<&str> {
        self.payload.get("text").and_then(|s| s.as_str())
    }
}

/// Parse one NDJSON line into an [`Event`].
pub fn parse_line(line: &str) -> Result<Event> {
    let value: Value = serde_json::from_str(line).context("invalid JSON line")?;
    let version = value
        .get("v")
        .and_then(|v| v.as_u64())
        .context("missing protocol version field `v`")?;
    if version != 1 {
        bail!("unsupported protocol version: {version}");
    }
    let kind = value
        .get("type")
        .and_then(|t| t.as_str())
        .context("missing message type field `type`")?
        .to_string();
    if !KNOWN_V1_EVENT_TYPES.contains(&kind.as_str()) {
        bail!("unknown v1 event type: {kind}");
    }
    Ok(Event {
        version,
        kind,
        payload: value,
    })
}

/// Parse a full NDJSON transcript; unknown versions/types abort the parse.
pub fn parse_lines(lines: &[&str]) -> Result<Vec<Event>> {
    lines.iter().map(|l| parse_line(l)).collect()
}

/// Build one versioned request (prompt/command/shutdown/interrupt).
pub fn build_request(kind: &str, text: &str, steer: bool) -> String {
    match kind {
        "prompt" => {
            let mut request = serde_json::json!({
                "v": 1,
                "type": "prompt",
                "text": text,
            });
            if steer {
                request
                    .as_object_mut()
                    .unwrap()
                    .insert("steer".into(), Value::Bool(true));
            }
            request.to_string()
        }
        // A slash line from the composer rides the `command` request; the
        // server dispatches it through core.commands and answers with a
        // command_result event.
        "command" => serde_json::json!({
            "v": 1,
            "type": "command",
            "line": text,
        })
        .to_string(),
        other => serde_json::json!({ "v": 1, "type": other }).to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_every_golden_fixture_line() {
        let manifest = env!("CARGO_MANIFEST_DIR");
        let candidates = [
            format!("{manifest}/../tests/fixtures/serve_events_v1.jsonl"),
            format!("{manifest}/../../tests/fixtures/serve_events_v1.jsonl"),
        ];
        let text = candidates
            .iter()
            .find_map(|p| std::fs::read_to_string(p).ok())
            .expect("golden fixture must be readable from the crate");
        let lines: Vec<&str> = text.lines().filter(|l| !l.trim().is_empty()).collect();
        assert_eq!(lines.len(), 13, "fixture line count drifted");
        let events = parse_lines(&lines).expect("every fixture line must parse");
        let kinds: Vec<&str> = events.iter().map(|e| e.kind.as_str()).collect();
        for expected in KNOWN_V1_EVENT_TYPES {
            assert!(kinds.contains(&expected), "fixture lacks {expected}");
        }
    }

    #[test]
    fn rejects_unknown_version() {
        let err = parse_line(r#"{"v": 2, "type": "status"}"#).unwrap_err();
        assert!(err.to_string().contains("unsupported protocol version"));
    }

    #[test]
    fn rejects_unknown_type() {
        let err = parse_line(r#"{"v": 1, "type": "hover_widget"}"#).unwrap_err();
        assert!(err.to_string().contains("unknown v1 event type"));
    }

    #[test]
    fn rejects_missing_envelope() {
        assert!(parse_line(r#"{"type": "status"}"#).is_err());
        assert!(parse_line(r#"{"v": 1}"#).is_err());
        assert!(parse_line("not json").is_err());
    }

    #[test]
    fn builds_v1_requests() {
        assert!(build_request("shutdown", "", false).contains(r#""type":"shutdown""#));
        assert!(build_request("interrupt", "", false).contains(r#""type":"interrupt""#));
        let steer = build_request("prompt", "go left", true);
        assert!(steer.contains(r#""steer":true"#) && steer.contains(r#""text":"go left""#));
        let plain = build_request("prompt", "hi", false);
        assert!(!plain.contains("steer"));
    }

    #[test]
    fn builds_command_requests_with_line_field() {
        let request = build_request("command", "/keys", false);
        assert!(request.contains(r#""type":"command""#));
        assert!(request.contains(r#""line":"/keys""#));
        assert!(request.contains(r#""v":1"#));
    }

    #[test]
    fn command_result_payload_is_accepted() {
        let event = parse_line(
            r#"{"v": 1, "type": "command_result", "verb": "/keys", "output": ["{\"a\": true}"]}"#,
        )
        .unwrap();
        assert_eq!(event.kind, "command_result");
    }

    #[test]
    fn stage_and_text_accessors() {
        let event = parse_line(r#"{"v": 1, "type": "stream", "text": "hi"}"#).unwrap();
        assert_eq!(event.text(), Some("hi"));
        let status = parse_line(r#"{"v": 1, "type": "status", "stage": "ready"}"#).unwrap();
        assert_eq!(status.stage(), Some("ready"));
    }
}
