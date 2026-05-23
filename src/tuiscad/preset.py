"""Presets are runnable `.scad` files that contain *only* the diff from the
source defaults. They `include <source.scad>` and re-assign overridden vars
afterward — relying on OpenSCAD's "last assignment wins" semantics so the
overrides take effect even though the source has top-level rendering code.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import ScadModel, ScadValue

PRESET_HEADER = "// tuiscad-preset"
PRESET_NAME_KEY = "// name:"
PRESET_SOURCE_KEY = "// source:"
OVERRIDES_MARKER = "// === overrides ==="

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_INCLUDE_RE = re.compile(r"^\s*include\s*<(?P<path>[^>]+)>\s*;?\s*$")
_ASSIGN_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][\w]*)\s*=\s*(?P<value>.+?)\s*;\s*(?://.*)?\s*$")


@dataclass
class Preset:
    """A named set of overrides over a source `.scad`."""

    name: str
    source_path: Path
    """Path to the source .scad, relative to (or absolute next to) the preset."""
    overrides: dict[str, ScadValue] = field(default_factory=dict)
    preset_path: Path | None = None
    """Where this preset was/will be saved."""

    @property
    def slug(self) -> str:
        return slugify(self.name)

    def is_modified(self, name: str, default: ScadValue) -> bool:
        if name not in self.overrides:
            return False
        return not values_equal(self.overrides[name], default)

    def set_override(self, name: str, value: ScadValue, default: ScadValue) -> None:
        if values_equal(value, default):
            self.overrides.pop(name, None)
        else:
            self.overrides[name] = value

    def reset(self, name: str) -> None:
        self.overrides.pop(name, None)

    def to_scad(self) -> str:
        lines = [
            PRESET_HEADER,
            f"{PRESET_NAME_KEY} {self.name}",
            f"{PRESET_SOURCE_KEY} {self.source_path.as_posix()}",
            "",
            f"include <{self.source_path.as_posix()}>",
            "",
            OVERRIDES_MARKER,
        ]
        if not self.overrides:
            lines.append("// (no overrides — preset matches source defaults)")
        else:
            for name, value in self.overrides.items():
                lines.append(f"{name} = {format_scad_value(value)};")
        lines.append("")
        return "\n".join(lines)

    def save(self, path: Path | None = None) -> Path:
        target = path or self.preset_path
        if target is None:
            raise ValueError("preset has no path; pass `path=` to save()")
        target.write_text(self.to_scad(), encoding="utf-8")
        self.preset_path = target
        return target

    def resolved_source_path(self) -> Path:
        """Resolve the relative `source_path` against the preset's location."""
        if self.preset_path is None:
            return Path(self.source_path).resolve()
        return (self.preset_path.parent / self.source_path).resolve()


PRESET_SUFFIX = ".tui.scad"


def preset_filename(name: str) -> str:
    return f"{slugify(name)}{PRESET_SUFFIX}"


def is_preset_file(path: Path) -> bool:
    return path.name.endswith(PRESET_SUFFIX)


def slugify(name: str) -> str:
    return _SLUG_RE.sub("_", name.strip().lower()).strip("_") or "preset"


def values_equal(a: ScadValue, b: ScadValue) -> bool:
    """Numeric-aware equality. `1 == 1.0` and `[1,2] == [1.0, 2.0]`.

    Booleans are *not* equal to numerics — `True != 1` here, even though
    Python's `==` says otherwise.
    """
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return False
        return all(values_equal(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if isinstance(a, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return a == b


def format_scad_value(value: ScadValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        out = repr(value)
        # Drop trailing `.0` from floats with integral value for readability.
        if isinstance(value, float) and out.endswith(".0"):
            return out[:-2]
        return out
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(format_scad_value(v) for v in value) + "]"
    raise TypeError(f"unsupported value type: {type(value).__name__}")


def load_preset(path: Path) -> Preset:
    text = Path(path).read_text(encoding="utf-8")
    name: str | None = None
    source: str | None = None
    overrides: dict[str, ScadValue] = {}
    seen_overrides_marker = False

    # Lazy import to avoid cycle.
    from .parser import _parse_value

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith(PRESET_NAME_KEY):
            name = line[len(PRESET_NAME_KEY) :].strip()
            continue
        if line.startswith(PRESET_SOURCE_KEY):
            source = line[len(PRESET_SOURCE_KEY) :].strip()
            continue
        if line.strip() == OVERRIDES_MARKER:
            seen_overrides_marker = True
            continue
        if not seen_overrides_marker:
            # Fall back: also recognize `include <...>` to pin source.
            m_inc = _INCLUDE_RE.match(line)
            if m_inc and source is None:
                source = m_inc.group("path").strip()
            continue
        if not line.strip() or line.strip().startswith("//"):
            continue
        m = _ASSIGN_RE.match(line)
        if m:
            try:
                v, _ = _parse_value(m.group("value").strip())
            except Exception:
                v = m.group("value").strip()
            overrides[m.group("name")] = v

    if name is None or source is None:
        raise ValueError(f"{path} does not look like a tuiscad preset")

    return Preset(
        name=name,
        source_path=Path(source),
        overrides=overrides,
        preset_path=Path(path),
    )


def discover_presets(
    source_path: Path | None, search_dir: Path, *, recursive: bool = True
) -> list[Preset]:
    """Return all `.tui.scad` presets under `search_dir`.

    If `source_path` is provided, only presets whose `// source:` header
    resolves to that file are returned. Pass `None` to list every preset.
    """
    pattern = "**/*" + PRESET_SUFFIX if recursive else "*" + PRESET_SUFFIX
    out: list[Preset] = []
    target = source_path.resolve() if source_path is not None else None
    for candidate in sorted(search_dir.glob(pattern)):
        try:
            preset = load_preset(candidate)
        except Exception:
            continue
        if target is None or preset.resolved_source_path() == target:
            out.append(preset)
    return out


def new_preset(
    name: str, source_path: Path, search_dir: Path, model: ScadModel | None = None
) -> Preset:
    """Create a new preset (not saved). Use `.save()` to persist.

    The stored ``source_path`` is computed relative to ``search_dir`` so
    OpenSCAD's ``include <...>`` resolves correctly regardless of where the
    source lives relative to the preset.
    """
    _ = model  # reserved for future validation
    preset_path = search_dir / preset_filename(name)
    rel_source = Path(os.path.relpath(Path(source_path).resolve(), Path(search_dir).resolve()))
    return Preset(
        name=name,
        source_path=rel_source,
        preset_path=preset_path,
    )
