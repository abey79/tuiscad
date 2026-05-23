"""Parse the OpenSCAD customizer-recognized parameters from a `.scad` file.

Mirrors OpenSCAD's behavior: only top-level variables before the first `module`
or `function` declaration (or a `/* [Hidden] */` group) are considered. Each
parameter may have a description (the `// ...` comment line(s) immediately
above) and a widget hint (a trailing `// ...` on the assignment line).
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import (
    DropdownOption,
    Hint,
    Parameter,
    ParamKind,
    ScadModel,
    ScadValue,
)

_GROUP_RE = re.compile(r"^\s*/\*\s*\[(?P<label>[^\]]+)\]\s*\*/\s*$")
_STOP_RE = re.compile(r"^\s*(module|function)\s+\w+")
_DESC_RE = re.compile(r"^\s*//\s?(?P<text>.*)$")
_BLOCK_OPEN_RE = re.compile(r"^\s*/\*")
_BLOCK_CLOSE_RE = re.compile(r"\*/\s*$")
# A variable assignment line: name = value; optional trailing // hint
_ASSIGN_RE = re.compile(
    r"^\s*(?P<name>[A-Za-z_][\w]*)\s*=\s*(?P<value>.+?)\s*;\s*(?://\s*(?P<hint>.*))?\s*$"
)


def parse_scad(path: Path) -> ScadModel:
    text = Path(path).read_text(encoding="utf-8")
    return parse_source(text, source_path=Path(path))


def parse_source(text: str, source_path: Path = Path("<memory>")) -> ScadModel:
    model = ScadModel(source_path=source_path)
    current_group = ""
    pending_description: list[str] = []
    in_block_comment = False

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line

        # Multi-line block comment skipping (but single-line group markers
        # still need to be detected, so we only skip *interior* lines here).
        if in_block_comment:
            if _BLOCK_CLOSE_RE.search(line):
                in_block_comment = False
            pending_description = []
            continue

        # Stop conditions
        if _STOP_RE.match(line):
            break

        # Group / Hidden marker (single-line block comments)
        m_group = _GROUP_RE.match(line)
        if m_group:
            label = m_group.group("label").strip()
            if label.lower() == "hidden":
                break
            current_group = label
            if label not in model.groups:
                model.groups.append(label)
            pending_description = []
            continue

        # Multi-line block comment open without close on same line: skip body
        if _BLOCK_OPEN_RE.match(line) and not _BLOCK_CLOSE_RE.search(line):
            in_block_comment = True
            pending_description = []
            continue

        stripped = line.strip()

        # Empty line resets pending description
        if not stripped:
            pending_description = []
            continue

        # Description comment (// ...)
        m_desc = _DESC_RE.match(line)
        if m_desc and not _ASSIGN_RE.match(line):
            pending_description.append(m_desc.group("text").rstrip())
            continue

        # Variable assignment
        m_assign = _ASSIGN_RE.match(line)
        if m_assign:
            name = m_assign.group("name")
            value_str = m_assign.group("value").strip()
            hint_str = (m_assign.group("hint") or "").strip()

            # Skip OpenSCAD special variables ($fa, $fs, $fn) — they're set
            # programmatically near the bottom and aren't customizer params.
            if name.startswith("$"):
                pending_description = []
                continue

            try:
                default, kind = _parse_value(value_str)
            except _ParseError:
                default, kind = value_str, ParamKind.UNKNOWN

            hint = _parse_hint(hint_str) if hint_str else None

            param = Parameter(
                name=name,
                default=default,
                kind=kind,
                raw_value=value_str,
                description=" ".join(s.strip() for s in pending_description).strip(),
                group=current_group,
                hint=hint,
                line_no=line_no,
            )
            model.parameters.append(param)
            pending_description = []
            continue

        # Anything else: reset pending description
        pending_description = []

    return model


# --- Value parsing --------------------------------------------------------


class _ParseError(Exception):
    pass


def _parse_value(text: str) -> tuple[ScadValue, ParamKind]:
    text = text.strip()
    if not text:
        raise _ParseError("empty value")

    if text == "true":
        return True, ParamKind.BOOL
    if text == "false":
        return False, ParamKind.BOOL

    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return text[1:-1], ParamKind.STRING

    if text.startswith("[") and text.endswith("]"):
        items = _split_bracket_items(text[1:-1])
        parsed: list[ScadValue] = []
        for item in items:
            v, _ = _parse_value(item)
            parsed.append(v)
        return parsed, ParamKind.VECTOR

    # Numeric
    try:
        if "." in text or "e" in text or "E" in text:
            return float(text), ParamKind.NUMBER
        return int(text), ParamKind.NUMBER
    except ValueError as exc:
        raise _ParseError(f"unparseable value: {text!r}") from exc


def _split_bracket_items(body: str) -> list[str]:
    """Split a `[...]` body on commas at depth 0, respecting nesting and strings."""
    items: list[str] = []
    buf: list[str] = []
    depth = 0
    in_string = False
    i = 0
    while i < len(body):
        ch = body[i]
        if in_string:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(body):
                buf.append(body[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            buf.append(ch)
        elif ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        items.append("".join(buf).strip())
    return [it for it in items if it != ""]


# --- Hint parsing ---------------------------------------------------------


def _parse_hint(text: str) -> Hint:
    """Parse a trailing `// ...` annotation into a Hint.

    Recognized forms:
      `0.1` or `.1`            → step
      `[a:c]`                  → range min..max (step 1)
      `[a:b:c]`                → range min..max with step b
      `[a, b, c]`              → dropdown of bare values
      `[a:Label, b:"Label"]`   → labeled dropdown
    """
    raw = text.strip()
    if not raw:
        return Hint(raw=raw)

    if raw.startswith("[") and raw.endswith("]"):
        return _parse_bracketed_hint(raw, raw_text=raw)

    # Bare numeric → step
    try:
        return Hint(step=float(raw), raw=raw)
    except ValueError:
        return Hint(raw=raw)


def _parse_bracketed_hint(text: str, raw_text: str) -> Hint:
    body = text[1:-1].strip()
    if not body:
        return Hint(raw=raw_text)

    items = _split_bracket_items(body)

    # If any item contains a comma at top level — already split. The decision:
    # if there are commas (i.e., multiple items), it's a dropdown.
    if len(items) > 1:
        opts = tuple(_parse_dropdown_item(it) for it in items)
        return Hint(options=opts, raw=raw_text)

    # Single item — could be range "a:b" / "a:b:c" or a single dropdown.
    single = items[0]
    parts = _split_top_level_colon(single)
    if len(parts) >= 2 and all(_looks_numeric(p) for p in parts):
        nums = [float(p) for p in parts]
        if len(nums) == 2:
            return Hint(min=nums[0], max=nums[1], step=1.0, raw=raw_text)
        return Hint(min=nums[0], step=nums[1], max=nums[2], raw=raw_text)

    # Otherwise treat as a single-option dropdown.
    return Hint(options=(_parse_dropdown_item(single),), raw=raw_text)


def _parse_dropdown_item(item: str) -> DropdownOption:
    parts = _split_top_level_colon(item, limit=2)
    if len(parts) == 1:
        v_str = parts[0].strip()
        try:
            v, _ = _parse_value(v_str)
        except _ParseError:
            v = v_str
        return DropdownOption(value=v, label=str(v))
    v_str, label = parts[0].strip(), parts[1].strip()
    try:
        v, _ = _parse_value(v_str)
    except _ParseError:
        v = v_str
    label_clean = label[1:-1] if (label.startswith('"') and label.endswith('"')) else label
    return DropdownOption(value=v, label=label_clean)


def _split_top_level_colon(text: str, limit: int = -1) -> list[str]:
    """Split on `:` not inside quotes/brackets."""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            buf.append(ch)
            if ch == "\\" and i + 1 < len(text):
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            buf.append(ch)
        elif ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth -= 1
            buf.append(ch)
        elif ch == ":" and depth == 0 and (limit < 0 or len(out) < limit - 1):
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


def _looks_numeric(s: str) -> bool:
    s = s.strip()
    try:
        float(s)
        return True
    except ValueError:
        return False
