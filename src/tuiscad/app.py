"""The Textual application: open a `.scad` file, edit a named preset's diff."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Header,
    ListItem,
    ListView,
    Static,
    Tree,
)

from .models import Parameter, ScadModel, ScadValue
from .parser import parse_scad
from .preset import (
    Preset,
    discover_presets,
    load_preset,
    new_preset,
    preset_filename,
    preset_name,
    values_equal,
)
from .screens import ConfirmScreen, ModelPickerScreen, NewPresetScreen
from .treebrowse import NewPresetHere, PresetTree
from .widgets import ParameterRow

GROUP_ANY = "(no group)"


class StatusBar(Static):
    """One-line status: source file, active preset, modified count."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $primary 30%;
        color: $text;
        padding: 0 1;
    }
    """


class TuiscadApp(App[None]):
    CSS = """
    Screen {
        layers: base modal;
    }
    #main-grid {
        height: 1fr;
    }
    #sidebar {
        background: $surface;
        padding: 1;
        border-right: solid $primary 30%;
    }
    .sidebar-title-groups {
        border-top: solid $primary 30%;
        padding-top: 1;
    }
    #params-pane {
        width: 1fr;
        padding: 0 1;
    }
    .sidebar-title {
        color: $text;
        text-style: bold;
        margin-top: 1;
    }
    .sidebar-title.first {
        margin-top: 0;
    }
    .group-header {
        background: $primary 25%;
        color: $text;
        text-style: bold;
        padding: 0 1;
        margin-top: 1;
        margin-bottom: 1;
        border-top: heavy $primary;
        border-bottom: solid $primary 50%;
        height: auto;
    }
    .group-header.first {
        margin-top: 0;
    }
    .group-modified-badge {
        color: $warning;
        text-style: italic;
    }
    .empty-state {
        color: $text-muted;
        padding: 1 2;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+s", "save_preset", "Save", show=True),
        Binding("n", "new_preset", "New preset", show=True),
        Binding("m", "toggle_modified", "Modified only", show=True),
        Binding("o", "open_openscad", "Open in OpenSCAD", show=True),
        Binding("e", "export_stl", "Export STL", show=True),
        Binding("d", "duplicate_preset", "Duplicate", show=True),
        Binding("r", "rename_preset", "Rename", show=True),
        Binding("delete", "delete_preset", "Delete", show=True),
        Binding("R", "reset_all", "Reset all", show=False),
    ]

    OPENSCAD_FALLBACK = "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"

    show_modified_only: reactive[bool] = reactive(False)
    """When true, hide parameters whose value matches the source default."""

    def __init__(
        self,
        source_path: Path | None = None,
        search_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.search_dir = (search_dir or Path.cwd()).resolve()
        self.source_path: Path | None = (
            Path(source_path).resolve() if source_path is not None else None
        )
        self.model: ScadModel = (
            parse_scad(self.source_path)
            if self.source_path is not None
            else ScadModel(source_path=Path("<none>"))
        )
        # Discover *all* presets in the search dir (regardless of source) so
        # the sidebar can navigate across models.
        self.presets: list[Preset] = discover_presets(None, self.search_dir)
        self.active_preset: Preset | None = None
        self._dirty: bool = False
        self._render_seq: int = 0

    # --- Lifecycle ---------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatusBar(self._status_line(), id="status")
        with Horizontal(id="main-grid"):
            with Vertical(id="sidebar"):
                yield Static("Presets", classes="sidebar-title first")
                yield PresetTree(self.search_dir, self.presets, id="preset-tree")
                yield Static("Groups", classes="sidebar-title sidebar-title-groups")
                yield ListView(id="group-list")
            with VerticalScroll(id="params-pane"):
                yield Static(
                    "Press [b]n[/] to create a preset, then start editing.",
                    classes="empty-state",
                    id="empty-state",
                )
        yield Footer()

    def on_mount(self) -> None:
        self._populate_preset_list()
        self._populate_group_list()
        self._render_params()
        self._size_sidebar()
        self.screen.refresh(layout=True)

    def on_resize(self) -> None:
        self._size_sidebar()

    def _size_sidebar(self) -> None:
        """Auto-size the sidebar to fit its widest *actually-rendered* line,
        capped at 40% of the screen (and a hard 60-cell ceiling)."""
        # PresetTree contents (root + leaves), each at a tree depth that adds
        # ~2*depth chars of indent + 2 chars of chevron/leaf marker.
        TREE_CHROME = 4  # indent + leaf marker for depth-1 nodes
        NEW_HERE_LITERAL = 19  # "[+] new preset here"

        # Root label = search-dir name, no indent.
        widest = max(16, len(self.search_dir.name) + 2)

        # Leaves at depth 1: presets + the "[+] new preset here" markers.
        widest = max(widest, NEW_HERE_LITERAL + TREE_CHROME)
        for preset in self.presets:
            widest = max(widest, len(preset.name) + TREE_CHROME)

        # Subdirs at depth 1 (then their leaves at depth 2…). Cheap proxy:
        # use any directory we've seen presets in.
        for preset in self.presets:
            if preset.preset_path is None:
                continue
            try:
                rel = preset.preset_path.parent.relative_to(self.search_dir)
            except ValueError:
                continue
            for i, part in enumerate(rel.parts):
                # depth = i+1 → indent = 2*(i+1)
                widest = max(widest, len(part) + 2 * (i + 1) + 2)

        # Group ListView lines: "Base Plate Options  (3/15)" — content + ~9.
        for group in self.model.groups:
            widest = max(widest, len(group) + 9)
        if any(p.group == "" for p in self.model.parameters):
            widest = max(widest, len("(no group)") + 9)

        # +2 padding, +1 border-right.
        target = widest + 3
        screen_width = self.size.width or 80
        cap = min(60, int(screen_width * 0.4))
        target = max(20, min(target, cap))
        try:
            sidebar = self.query_one("#sidebar")
            sidebar.styles.width = target
        except Exception:
            pass

    # --- Population --------------------------------------------------------

    def _populate_preset_list(self) -> None:
        try:
            tree = self.query_one("#preset-tree", PresetTree)
        except Exception:
            return
        tree.update_presets(self.presets)
        if self._widgets_ready:
            self._size_sidebar()

    def _populate_group_list(self) -> None:
        lv = self.query_one("#group-list", ListView)
        if self._widgets_ready:
            self._size_sidebar()
        groups: list[str] = []
        if any(p.group == "" for p in self.model.parameters):
            groups.append("")
        for g in self.model.groups:
            groups.append(g)
        # Update existing labels in place if possible (avoids DuplicateIds racing
        # with the async ListView.clear). Build any missing items.
        existing = {child.id: child for child in lv.children if child.id}
        seen_ids: set[str] = set()
        for g in groups:
            label = g if g else GROUP_ANY
            count = sum(1 for p in self.model.parameters if p.group == g)
            modified = sum(
                1 for p in self.model.parameters if p.group == g and self._is_modified(p)
            )
            txt = f"{label}  ({modified}/{count})" if modified else f"{label}  ({count})"
            slug = (g or "general").lower().replace(" ", "_")
            item_id = f"group-{slug}"
            seen_ids.add(item_id)
            if item_id in existing:
                static = existing[item_id].query_one(Static)
                static.update(txt)
            else:
                lv.append(ListItem(Static(txt), id=item_id))
        for child_id, child in existing.items():
            if child_id not in seen_ids:
                child.remove()

    def _render_params(self) -> None:
        pane = self.query_one("#params-pane", VerticalScroll)
        self._render_seq += 1
        for child in list(pane.children):
            child.remove()
        # `remove()` is async — its DOM cleanup may not have run yet, so
        # we tag fresh widgets with a render-sequence suffix to avoid id
        # collisions with the about-to-be-removed previous batch.
        if self.active_preset is None:
            if self.source_path is None:
                msg = (
                    "No model loaded.\n\n"
                    "Pick a preset from the sidebar (its source loads automatically), "
                    "or press [b]n[/] to create a new preset and choose a model."
                )
            else:
                msg = (
                    f"Press [b]n[/] to create a preset before editing.\nSource: {self.source_path}"
                )
            pane.mount(Static(msg, classes="empty-state"))
            return

        groups: list[str] = []
        if any(p.group == "" for p in self.model.parameters):
            groups.append("")
        for g in self.model.groups:
            groups.append(g)

        rendered_any = False
        first_group = True
        for group in groups:
            params_in_group = [p for p in self.model.parameters if p.group == group]
            if self.show_modified_only:
                params_in_group = [p for p in params_in_group if self._is_modified(p)]
            if not params_in_group:
                continue
            rendered_any = True
            slug = (group or "general").lower().replace(" ", "_")
            label = group if group else GROUP_ANY
            modified_count = sum(1 for p in params_in_group if self._is_modified(p))
            header_text = f"▾ {label}"
            if modified_count:
                header_text += f"   [italic]({modified_count} modified)[/italic]"
            classes = ["group-header", f"group-{slug}"]
            if first_group:
                classes.append("first")
            pane.mount(
                Static(
                    header_text,
                    classes=" ".join(classes),
                    id=f"groupheader-{slug}-{self._render_seq}",
                )
            )
            first_group = False
            for param in params_in_group:
                row = ParameterRow(
                    param=param,
                    current=self._current_value(param),
                    on_change=self._on_param_changed,
                    editable=True,
                    suffix=str(self._render_seq),
                )
                pane.mount(row)

        if not rendered_any:
            pane.mount(
                Static(
                    "(nothing to show — toggle [b]m[/] to see all parameters)",
                    classes="empty-state",
                )
            )

    # --- Status / state ----------------------------------------------------

    def _status_line(self) -> str:
        src = self.source_path.name if self.source_path is not None else "(no model)"
        if self.active_preset is None:
            return f"  {src}    (no preset — read-only)"
        modified = sum(1 for p in self.model.parameters if self._is_modified(p))
        dirty = " *" if self._dirty else ""
        return f"  {src}    preset: [b]{self.active_preset.name}[/]    modified: {modified}{dirty}"

    def _refresh_status(self) -> None:
        self.query_one("#status", StatusBar).update(self._status_line())

    def _is_modified(self, param: Parameter) -> bool:
        return not values_equal(self._current_value(param), param.default)

    def _current_value(self, param: Parameter) -> ScadValue:
        if self.active_preset and param.name in self.active_preset.overrides:
            return self.active_preset.overrides[param.name]
        return param.default

    # --- Param change handler ---------------------------------------------

    def _on_param_changed(self, name: str, value: ScadValue | None) -> None:
        if self.active_preset is None:
            return
        param = self.model.by_name(name)
        if param is None:
            return
        if value is None:
            self.active_preset.reset(name)
        else:
            self.active_preset.set_override(name, value, param.default)
        self._dirty = True
        # Update the row's current value in case it was a reset.
        for row in self.query(ParameterRow):
            if row.param.name == name:
                row.update_current(self._current_value(param))
                break
        self._refresh_status()
        self._populate_group_list()
        # Auto-save: write to disk on every change.
        self._save_preset_silently()

    # --- Actions -----------------------------------------------------------

    def action_save_preset(self) -> None:
        if self.active_preset is None:
            self.notify("No active preset.", severity="warning")
            return
        path = self._save_preset_silently()
        if path is not None:
            self.notify(f"Saved → {path.name}")

    def _save_preset_silently(self) -> Path | None:
        if self.active_preset is None:
            return None
        target = self.active_preset.preset_path or self.search_dir / preset_filename(
            self.active_preset.name
        )
        path = self.active_preset.save(target)
        self._dirty = False
        if not any(p.preset_path == path for p in self.presets):
            self.presets.append(self.active_preset)
            self._populate_preset_list()
        self._refresh_status()
        return path

    def action_new_preset(self) -> None:
        self._start_new_preset_flow(self.search_dir)

    def _start_new_preset_flow(self, target_dir: Path) -> None:
        """Pick a model, name a preset, save it under `target_dir`."""
        target_dir = target_dir.resolve()

        def _finish(picked_source: Path, name: str | None) -> None:
            if name is None:
                return
            if self.source_path is None or picked_source.resolve() != self.source_path:
                self._load_source(picked_source)
            assert self.source_path is not None  # _load_source set it
            preset = new_preset(name, self.source_path, target_dir, self.model)
            target_dir.mkdir(parents=True, exist_ok=True)
            self.active_preset = preset
            self._save_preset_silently()
            # Refresh discovery so the tree picks up the new file.
            self.presets = discover_presets(None, self.search_dir)
            self._populate_preset_list()
            self._render_params()
            self._refresh_status()

        def _on_source(picked_source: Path | None) -> None:
            if picked_source is None:
                return
            self.push_screen(
                NewPresetScreen(),
                lambda name: _finish(picked_source, name),
            )

        self.push_screen(ModelPickerScreen(self.search_dir), _on_source)

    def _load_source(self, source_path: Path) -> None:
        """Switch the active source `.scad`. Drops the active preset."""
        self.source_path = source_path.resolve()
        self.model = parse_scad(self.source_path)
        self.presets = discover_presets(None, self.search_dir)
        self.active_preset = None
        self._dirty = False
        self._populate_preset_list()
        self._populate_group_list()
        self._render_params()
        self._refresh_status()

    def action_toggle_modified(self) -> None:
        self.show_modified_only = not self.show_modified_only

    def action_open_openscad(self) -> None:
        if self.active_preset is None:
            self.notify(
                "Create a preset first — OpenSCAD opens the preset file.",
                severity="warning",
            )
            return
        path = self._save_preset_silently()
        if path is None:
            return
        binary = self._resolve_openscad()
        if binary is None:
            self.notify(
                "OpenSCAD not found. Set $OPENSCAD_BIN or install openscad on PATH.",
                severity="error",
            )
            return
        try:
            subprocess.Popen(
                [binary, str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self.notify(f"Opened {path.name} in OpenSCAD.")
        except OSError as exc:
            self.notify(f"Failed to launch OpenSCAD: {exc}", severity="error")

    def action_export_stl(self) -> None:
        if self.active_preset is None:
            self.notify("Create a preset first.", severity="warning")
            return
        preset_path = self._save_preset_silently()
        if preset_path is None:
            return
        binary = self._resolve_openscad()
        if binary is None:
            self.notify(
                "OpenSCAD not found. Set $OPENSCAD_BIN or install openscad on PATH.",
                severity="error",
            )
            return
        # Strip the full `.tui.scad` suffix, append `.stl`.
        stem = preset_path.name.removesuffix(".tui.scad")
        if stem == preset_path.name:  # safety: not actually a preset suffix
            stem = preset_path.stem
        out_path = preset_path.with_name(f"{stem}.stl")
        self.run_worker(
            self._do_export_stl(binary, preset_path, out_path),
            exclusive=True,
            group="export-stl",
        )

    async def _do_export_stl(self, binary: str, preset_path: Path, out_path: Path) -> None:
        self.notify(f"Rendering {out_path.name}…", timeout=10)
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                "-o",
                str(out_path),
                "--export-format=binstl",
                str(preset_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
        except OSError as exc:
            self.notify(f"Failed to start OpenSCAD: {exc}", severity="error")
            return
        if proc.returncode == 0 and out_path.exists():
            size_kb = out_path.stat().st_size / 1024
            self.notify(
                f"Exported {out_path.name}  ({size_kb:.1f} KiB)",
                severity="information",
                timeout=8,
            )
        else:
            tail = stderr.decode(errors="replace").strip().splitlines()[-3:]
            msg = " | ".join(tail) or f"exit code {proc.returncode}"
            self.notify(f"OpenSCAD failed: {msg}", severity="error", timeout=10)

    def _resolve_openscad(self) -> str | None:
        return (
            os.environ.get("OPENSCAD_BIN")
            or shutil.which("openscad")
            or (self.OPENSCAD_FALLBACK if Path(self.OPENSCAD_FALLBACK).exists() else None)
        )

    def action_duplicate_preset(self) -> None:
        original = self.active_preset
        original_path = original.preset_path if original is not None else None
        if original is None or original_path is None:
            self.notify("No preset to duplicate.", severity="warning")
            return
        target_dir = original_path.parent
        suggested = f"{original.name} copy"

        def _on_name(name: str | None) -> None:
            if name is None:
                return
            new_path = target_dir / preset_filename(name)
            if new_path.exists():
                self.notify(
                    f"A preset file already exists at {new_path.name}.",
                    severity="error",
                )
                return
            clone = Preset(
                name=preset_name(new_path),
                source_path=original.source_path,
                overrides=dict(original.overrides),
                preset_path=new_path,
            )
            clone.save()
            self.presets = discover_presets(None, self.search_dir)
            self.active_preset = clone
            self._populate_preset_list()
            self._render_params()
            self._refresh_status()
            self.notify(f"Duplicated → {new_path.name}")

        self.push_screen(
            NewPresetScreen(
                title="Duplicate preset",
                help_text=(
                    f"Cloning [b]{original.name}[/] including all "
                    f"{len(original.overrides)} override(s). Pick a new name."
                ),
                initial=suggested,
                confirm_label="Duplicate",
            ),
            _on_name,
        )

    def action_rename_preset(self) -> None:
        original = self.active_preset
        original_path = original.preset_path if original is not None else None
        if original is None or original_path is None:
            self.notify("No preset to rename.", severity="warning")
            return
        target_dir = original_path.parent
        old_name = original.name
        # The STL export names itself after the preset stem, so a sibling
        # `<name>.stl` is "the" matching STL.
        old_stl = original_path.with_name(f"{old_name}.stl")

        def _apply(new_path: Path, rename_stl: bool) -> None:
            try:
                original_path.rename(new_path)
            except OSError as exc:
                self.notify(f"Failed to rename: {exc}", severity="error")
                return
            if rename_stl:
                new_stl = new_path.with_name(f"{preset_name(new_path)}.stl")
                try:
                    old_stl.rename(new_stl)
                except OSError as exc:
                    self.notify(
                        f"Preset renamed, but STL rename failed: {exc}",
                        severity="error",
                    )
            self.presets = discover_presets(None, self.search_dir)
            self.active_preset = next(
                (
                    p
                    for p in self.presets
                    if p.preset_path and p.preset_path.resolve() == new_path.resolve()
                ),
                None,
            )
            self._populate_preset_list()
            self._render_params()
            self._refresh_status()
            self.notify(f"Renamed → {new_path.name}")

        def _on_name(name: str | None) -> None:
            if name is None:
                return
            new_path = target_dir / preset_filename(name)
            if new_path.resolve() == original_path.resolve():
                return  # unchanged
            if new_path.exists():
                self.notify(
                    f"A preset file already exists at {new_path.name}.",
                    severity="error",
                )
                return
            if old_stl.exists():
                # Ask whether to rename the sibling STL too. Declining still
                # renames the preset — the question is only about the STL.
                self.push_screen(
                    ConfirmScreen(
                        title="Rename matching STL?",
                        message=(
                            f"[b]{old_stl.name}[/] matches this preset. "
                            "Rename it to match the new name too?"
                        ),
                        confirm_label="Rename STL",
                        confirm_variant="primary",
                    ),
                    lambda confirmed: _apply(new_path, bool(confirmed)),
                )
            else:
                _apply(new_path, False)

        self.push_screen(
            NewPresetScreen(
                title="Rename preset",
                help_text=(f"Renaming [b]{old_name}[/]. The preset's file is renamed to match."),
                initial=old_name,
                confirm_label="Rename",
            ),
            _on_name,
        )

    def action_delete_preset(self) -> None:
        target = self.active_preset
        target_path = target.preset_path if target is not None else None
        if target is None or target_path is None:
            self.notify("No preset to delete.", severity="warning")
            return

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            try:
                target_path.unlink()
            except OSError as exc:
                self.notify(f"Failed to delete: {exc}", severity="error")
                return
            self.notify(f"Deleted {target_path.name}")
            self.active_preset = None
            self._dirty = False
            self.presets = discover_presets(None, self.search_dir)
            self._populate_preset_list()
            self._render_params()
            self._refresh_status()

        self.push_screen(
            ConfirmScreen(
                title="Delete preset?",
                message=(
                    f"This will permanently delete [b]{target_path.name}[/]. "
                    f"({len(target.overrides)} override(s) will be lost.)"
                ),
                confirm_label="Delete",
            ),
            _on_confirm,
        )

    def action_reset_all(self) -> None:
        if self.active_preset is None:
            return
        self.active_preset.overrides.clear()
        self._dirty = True
        self._save_preset_silently()
        self._render_params()
        self._populate_group_list()
        self._refresh_status()

    def watch_show_modified_only(self, _value: bool) -> None:
        if self._widgets_ready:  # pragma: no branch
            self._render_params()

    # --- Sidebar selection -------------------------------------------------

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._handle_sidebar_pick(event.item.id or "")

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        # Group sidebar reacts to highlight (arrow-key navigation) too.
        if event.item is None:
            return
        item_id = event.item.id or ""
        if item_id.startswith("group-"):
            self._handle_sidebar_pick(item_id)

    def on_tree_node_selected(self, event: Tree.NodeSelected[Any]) -> None:
        data = event.node.data
        if isinstance(data, NewPresetHere):
            self._start_new_preset_flow(data.directory)
            return
        if isinstance(data, Path) and data.is_file():
            self._activate_preset_file(data)

    def _activate_preset_file(self, path: Path) -> None:
        try:
            preset = load_preset(path)
        except Exception as exc:
            self.notify(f"Failed to load {path.name}: {exc}", severity="error")
            return
        preset_source = preset.resolved_source_path()
        if preset_source != self.source_path and preset_source.exists():
            self._load_source(preset_source)
        # Find the canonical instance from self.presets (so updates persist).
        canonical = next(
            (
                p
                for p in self.presets
                if p.preset_path and p.preset_path.resolve() == path.resolve()
            ),
            preset,
        )
        self.active_preset = canonical
        self._render_params()
        self._populate_preset_list()
        self._refresh_status()

    def _handle_sidebar_pick(self, item_id: str) -> None:
        if item_id.startswith("group-"):
            slug = item_id.removeprefix("group-")
            self._scroll_to_group(slug)

    def _scroll_to_group(self, slug: str) -> None:
        # Group headers carry a `group-{slug}` class. The id has a render-seq
        # suffix so we can't query by id; pick the first matching class.
        targets = list(self.query(f".group-{slug}"))
        if not targets:
            return
        targets[0].scroll_visible(top=True)

    @property
    def _widgets_ready(self) -> bool:
        """True once compose() has run and the status bar is queryable.

        Some helpers run before mount (in __init__ → on_mount chain) where
        `query_one` would raise; this gate lets them skip the UI bits.
        """
        try:
            self.query_one("#status", StatusBar)
            return True
        except Exception:
            return False
