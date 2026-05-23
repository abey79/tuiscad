"""Walk a directory looking for OpenSCAD models, classifying each as
either a top-level renderable model or a library/dependency.

The classification is purely path/name-based — fast and deterministic, and
sufficient for layouts where libraries live under `modules/` or follow the
``module_*.scad`` / ``functions_*.scad`` naming convention. Files that don't
match these heuristics are treated as models. A "show libraries" toggle in
the UI lets the user override when the heuristic gets it wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .preset import is_preset_file

LIBRARY_DIR_NAMES: frozenset[str] = frozenset({"modules", "module"})
LIBRARY_FILENAME_PREFIXES: tuple[str, ...] = ("module_", "functions_", "function_")
LIBRARY_FILENAME_SUFFIXES: tuple[str, ...] = ("_constants.scad",)


def is_library(path: Path) -> bool:
    """Return True if `path` looks like a library/dependency, not a top-level model."""
    name = path.name.lower()
    if any(seg.lower() in LIBRARY_DIR_NAMES for seg in path.parts[:-1]):
        return True
    if any(name.startswith(p) for p in LIBRARY_FILENAME_PREFIXES):
        return True
    return any(name.endswith(s) for s in LIBRARY_FILENAME_SUFFIXES)


@dataclass(frozen=True)
class ScadFile:
    path: Path
    """Absolute or root-relative path."""
    relative_to: Path
    """Display root (typically the search dir)."""
    is_library: bool

    @property
    def display_path(self) -> Path:
        try:
            return self.path.relative_to(self.relative_to)
        except ValueError:
            return self.path


def find_scad_files(root: Path, *, recursive: bool = True) -> list[ScadFile]:
    """Return all `.scad` files under `root`, excluding tuiscad presets.

    Sorted: models first (alphabetically), then libraries.
    """
    pattern = "**/*.scad" if recursive else "*.scad"
    found: list[ScadFile] = []
    for candidate in sorted(root.glob(pattern)):
        if not candidate.is_file():
            continue
        if is_preset_file(candidate):
            continue
        found.append(
            ScadFile(
                path=candidate.resolve(),
                relative_to=root.resolve(),
                is_library=is_library(candidate),
            )
        )
    found.sort(key=lambda f: (f.is_library, str(f.display_path).lower()))
    return found
