"""Tree-based browsers for presets and source models.

* :class:`PresetTree` — sidebar tree of `.tui.scad` files. Each directory
  carries a synthetic ``[+] new preset here`` leaf so the user can create
  a preset rooted at any subdirectory.
* :class:`ScadModelTree` — filtered DirectoryTree used in the picker;
  shows `.scad` files (excluding presets) and optionally hides libraries.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from textual.widgets import DirectoryTree, Tree
from textual.widgets.tree import TreeNode

from .discovery import is_library
from .preset import Preset, is_preset_file


@dataclass(frozen=True)
class NewPresetHere:
    """Synthetic tree-node payload meaning "create a new preset in this dir"."""

    directory: Path


PresetNodeData = Path | NewPresetHere


class PresetTree(Tree[PresetNodeData]):
    """Tree of tuiscad presets under a root directory.

    Every directory that contains (or recursively contains) presets is
    shown, with a leading ``[+] new preset here`` leaf. Files are leaf
    nodes labeled by the preset's `name` (falling back to the file stem
    for unparseable presets).
    """

    DEFAULT_CSS = """
    PresetTree {
        height: auto;
        max-height: 100%;
    }
    PresetTree > .tree--guides {
        color: $primary 30%;
    }
    """

    def __init__(self, root: Path, presets: list[Preset], **kwargs: object) -> None:
        root = root.resolve()
        super().__init__(label=root.name or str(root), data=root, **kwargs)  # type: ignore[arg-type]
        self.root_path = root
        self.presets = presets
        self.show_root = True

    def on_mount(self) -> None:
        self.rebuild()

    def update_presets(self, presets: list[Preset]) -> None:
        self.presets = presets
        self.rebuild()

    def rebuild(self) -> None:
        self.root.remove_children()
        self._populate(self.root, self.root_path)
        self.root.expand()

    # --- Internal ----------------------------------------------------------

    def _populate(self, node: TreeNode[PresetNodeData], directory: Path) -> None:
        node.add_leaf("[bold $accent][+] new preset here[/]", data=NewPresetHere(directory))

        subdirs: list[Path] = []
        preset_files: list[Path] = []
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir():
                if self._has_presets_recursive(entry):
                    subdirs.append(entry)
            elif entry.is_file() and is_preset_file(entry):
                preset_files.append(entry)

        for subdir in subdirs:
            sub = node.add(subdir.name, data=subdir, expand=True)
            self._populate(sub, subdir)

        preset_by_path = {
            (p.preset_path.resolve() if p.preset_path else None): p for p in self.presets
        }
        for preset_file in preset_files:
            preset_entry = preset_by_path.get(preset_file.resolve())
            label = preset_entry.name if preset_entry is not None else preset_file.stem
            node.add_leaf(label, data=preset_file)

    def _has_presets_recursive(self, directory: Path) -> bool:
        try:
            return any(directory.glob("**/*.tui.scad"))
        except OSError:
            return False


class ScadModelTree(DirectoryTree):
    """DirectoryTree filtered to `.scad` files (excluding presets), with an
    optional toggle for hiding library files (paths matching the library
    heuristic in :mod:`tuiscad.discovery`)."""

    def __init__(self, path: Path, *, show_libraries: bool = False, **kwargs: object) -> None:
        super().__init__(str(path), **kwargs)  # type: ignore[arg-type]
        self._show_libraries = show_libraries

    @property
    def show_libraries(self) -> bool:
        return self._show_libraries

    @show_libraries.setter
    def show_libraries(self, value: bool) -> None:
        self._show_libraries = value
        self.reload()

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        for p in paths:
            if p.is_dir():
                # Hide hidden dirs & vendored stuff that nobody wants.
                if p.name.startswith("."):
                    continue
                yield p
                continue
            if p.suffix != ".scad":
                continue
            if is_preset_file(p):
                continue
            if not self._show_libraries and is_library(p):
                continue
            yield p
