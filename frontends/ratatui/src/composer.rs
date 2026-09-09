//! Editable single-line composer state for the interactive frontend.

#[derive(Default)]
pub struct Composer {
    text: String,
    cursor: usize,
}

impl Composer {
    pub fn text(&self) -> &str {
        &self.text
    }

    pub fn cursor(&self) -> usize {
        self.cursor
    }

    pub fn clear(&mut self) {
        self.text.clear();
        self.cursor = 0;
    }

    pub fn insert_char(&mut self, ch: char) {
        self.text.insert(self.cursor, ch);
        self.cursor += ch.len_utf8();
    }

    pub fn insert_str(&mut self, text: &str) {
        let single_line = text.replace(['\r', '\n'], " ");
        self.text.insert_str(self.cursor, &single_line);
        self.cursor += single_line.len();
    }

    pub fn backspace(&mut self) {
        if let Some(previous) = self.previous_boundary() {
            self.text.drain(previous..self.cursor);
            self.cursor = previous;
        }
    }

    pub fn delete(&mut self) {
        if let Some(next) = self.next_boundary() {
            self.text.drain(self.cursor..next);
        }
    }

    pub fn move_left(&mut self) {
        if let Some(previous) = self.previous_boundary() {
            self.cursor = previous;
        }
    }

    pub fn move_right(&mut self) {
        if let Some(next) = self.next_boundary() {
            self.cursor = next;
        }
    }

    pub fn move_home(&mut self) {
        self.cursor = 0;
    }

    pub fn move_end(&mut self) {
        self.cursor = self.text.len();
    }

    fn previous_boundary(&self) -> Option<usize> {
        self.text[..self.cursor]
            .char_indices()
            .next_back()
            .map(|(index, _)| index)
    }

    fn next_boundary(&self) -> Option<usize> {
        self.text[self.cursor..]
            .char_indices()
            .nth(1)
            .map(|(index, _)| self.cursor + index)
            .or_else(|| (self.cursor < self.text.len()).then_some(self.text.len()))
    }
}

#[cfg(test)]
mod tests {
    use super::Composer;

    #[test]
    fn inserts_at_the_cursor_after_moving_left() {
        let mut composer = Composer::default();
        composer.insert_str("abc");
        composer.move_left();
        composer.insert_char('X');
        assert_eq!(composer.text(), "abXc");
        assert_eq!(composer.cursor(), 3);
    }

    #[test]
    fn delete_home_end_and_backspace_follow_character_boundaries() {
        // CJK (U+4E2D) and emoji (U+1F642) are written as escapes to
        // keep literal Chinese out of *.rs per the repo language policy.
        let zhong = "\u{4e2d}";
        let smile = "\u{1f642}";
        let mut composer = Composer::default();
        composer.insert_str(&format!("a{zhong}{smile}z"));
        composer.move_home();
        composer.delete();
        assert_eq!(composer.text(), format!("{zhong}{smile}z"));
        composer.move_end();
        composer.backspace();
        assert_eq!(composer.text(), format!("{zhong}{smile}"));
    }

    #[test]
    fn pasted_text_is_inserted_at_the_cursor() {
        let zhong = "\u{4e2d}";
        let smile = "\u{1f642}";
        let mut composer = Composer::default();
        composer.insert_str("ac");
        composer.move_left();
        composer.insert_str(&format!("{zhong}{smile}b"));
        assert_eq!(composer.text(), format!("a{zhong}{smile}bc"));
    }
}
