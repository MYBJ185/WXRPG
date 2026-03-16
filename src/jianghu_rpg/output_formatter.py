from __future__ import annotations

import re
from pathlib import Path

from rich.markup import escape


DEFAULT_RULES = {
    "paragraph_split": r"\n\s*\n+",
    "dialogue_quoted": r"[“\"「『][^”\"」』\n]{1,120}[”\"」』]",
    "dialogue_spoken_line": r"(^|\n)([\u4e00-\u9fffA-Za-z0-9_·]{1,16}[：:][^\n]{2,180})",
    "dialogue_turn": r"[\u4e00-\u9fffA-Za-z0-9_·]{1,16}[：:](?:(?![\u4e00-\u9fffA-Za-z0-9_·]{1,16}[：:]).){2,220}",
}


class OutputFormatter:
    def __init__(self, regex_path: Path) -> None:
        self.regex_path = regex_path
        self.rules = self._load_rules(regex_path)
        self.paragraph_split = self._compile("paragraph_split")
        self.dialogue_quoted = self._compile("dialogue_quoted")
        self.dialogue_spoken_line = self._compile("dialogue_spoken_line")
        self.dialogue_turn = self._compile("dialogue_turn")

    def format_narrative(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").strip()
        if not normalized:
            return ""
        base_paragraphs = [
            piece.strip()
            for piece in self.paragraph_split.split(normalized)
            if piece.strip()
        ]
        paragraphs: list[str] = []
        for paragraph in base_paragraphs:
            paragraphs.extend(self._split_dialogue_turns(paragraph))
        styled = [self._style_paragraph(paragraph) for paragraph in paragraphs if paragraph.strip()]
        return "\n\n".join(styled)

    def _style_paragraph(self, paragraph: str) -> str:
        escaped = escape(paragraph)
        escaped = self.dialogue_quoted.sub(
            lambda m: f"[bright_cyan]{m.group(0)}[/bright_cyan]",
            escaped,
        )
        escaped = self.dialogue_spoken_line.sub(
            lambda m: f"{m.group(1)}[bright_cyan]{m.group(2)}[/bright_cyan]",
            escaped,
        )
        return escaped

    def _split_dialogue_turns(self, paragraph: str) -> list[str]:
        if not self.dialogue_turn.search(paragraph):
            return [paragraph]
        chunks: list[str] = []
        cursor = 0
        for match in self.dialogue_turn.finditer(paragraph):
            before = paragraph[cursor : match.start()].strip()
            if before:
                chunks.append(before)
            chunks.append(match.group(0).strip())
            cursor = match.end()
        tail = paragraph[cursor:].strip()
        if tail:
            chunks.append(tail)
        return chunks or [paragraph]

    def _compile(self, key: str) -> re.Pattern[str]:
        pattern = self.rules.get(key, DEFAULT_RULES[key])
        return re.compile(pattern, flags=re.M)

    @staticmethod
    def _load_rules(regex_path: Path) -> dict[str, str]:
        rules = dict(DEFAULT_RULES)
        if not regex_path.exists():
            return rules
        for raw_line in regex_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key and value:
                rules[key] = value
        return rules
