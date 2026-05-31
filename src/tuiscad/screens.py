"""Modal screens (new-preset, model picker, etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label, Static, Switch

from .preset import is_preset_file
from .treebrowse import ScadModelTree


class NewPresetScreen(ModalScreen[str | None]):
    """Prompt the user for a preset name. Returns the name (or None on cancel)."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    NewPresetScreen {
        align: center middle;
    }
    NewPresetScreen > Vertical {
        width: 60;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: thick $primary;
    }
    NewPresetScreen Label.title {
        text-style: bold;
        margin-bottom: 1;
    }
    NewPresetScreen Static.help {
        color: $text-muted;
        margin-bottom: 1;
    }
    NewPresetScreen Input {
        margin-bottom: 1;
    }
    NewPresetScreen Horizontal.buttons {
        height: auto;
        align-horizontal: right;
    }
    NewPresetScreen Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        *,
        title: str = "Name your preset",
        help_text: str = (
            "Presets are saved as runnable .scad files. "
            "You must name a preset before editing parameters."
        ),
        initial: str = "",
        confirm_label: str = "Create",
    ) -> None:
        super().__init__()
        self._title = title
        self._help_text = help_text
        self._initial = initial
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title, classes="title")
            yield Static(self._help_text, classes="help")
            yield Input(
                value=self._initial,
                placeholder="e.g. drawers atelier 51x51 v2",
                id="preset-name",
            )
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self._confirm_label, id="confirm", variant="primary")

    def on_mount(self) -> None:
        inp = self.query_one("#preset-name", Input)
        inp.focus()
        if self._initial:
            inp.cursor_position = len(self._initial)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self._submit(self.query_one("#preset-name", Input).value)
        elif event.button.id == "cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _submit(self, name: str) -> None:
        name = name.strip()
        if not name:
            return
        self.dismiss(name)


class ConfirmScreen(ModalScreen[bool]):
    """Yes/No confirmation modal."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    ConfirmScreen > Vertical {
        width: 60;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: thick $error;
    }
    ConfirmScreen Label.title {
        text-style: bold;
        margin-bottom: 1;
    }
    ConfirmScreen Static.help {
        color: $text;
        margin-bottom: 1;
    }
    ConfirmScreen Horizontal.buttons {
        height: auto;
        align-horizontal: right;
    }
    ConfirmScreen Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        *,
        title: str,
        message: str,
        confirm_label: str = "Confirm",
        confirm_variant: str = "error",
    ) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label
        self._confirm_variant = confirm_variant

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title, classes="title")
            yield Static(self._message, classes="help")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(
                    self._confirm_label,
                    id="confirm",
                    variant=self._confirm_variant,  # type: ignore[arg-type]
                )

    def on_mount(self) -> None:
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)


class ModelPickerScreen(ModalScreen[Path | None]):
    """Pick the source `.scad` model that a new preset should target.

    Shows every `.scad` file under the current root (recursively), excluding
    tuiscad presets. Library files (those that look like dependencies based
    on path/filename heuristics) are hidden by default; a toggle reveals
    them. The user can re-root one level up at any time (the source `.scad`
    may live above cwd).
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
        ("u", "go_up", "Up"),
    ]

    DEFAULT_CSS = """
    ModelPickerScreen {
        align: center middle;
    }
    ModelPickerScreen > Vertical {
        width: 80;
        height: 30;
        padding: 1 2;
        background: $panel;
        border: thick $primary;
    }
    ModelPickerScreen Label.title {
        text-style: bold;
        margin-bottom: 1;
    }
    ModelPickerScreen Static.help {
        color: $text-muted;
        margin-bottom: 1;
    }
    ModelPickerScreen .root-row {
        height: auto;
        margin-bottom: 1;
    }
    ModelPickerScreen #current-root {
        width: 1fr;
        color: $text;
        content-align: left middle;
    }
    ModelPickerScreen #up-dir {
        min-width: 12;
    }
    ModelPickerScreen #file-list {
        height: 1fr;
        margin-bottom: 1;
    }
    ModelPickerScreen .toggle-row {
        height: auto;
        margin-bottom: 1;
    }
    ModelPickerScreen .toggle-row Label {
        margin-left: 1;
        width: auto;
    }
    ModelPickerScreen Switch {
        width: auto;
    }
    ModelPickerScreen Horizontal.buttons {
        height: auto;
        align-horizontal: right;
    }
    ModelPickerScreen Button {
        margin-left: 1;
    }
    """

    def __init__(self, search_dir: Path) -> None:
        super().__init__()
        self.search_dir = search_dir.resolve()
        self._root = self.search_dir
        self._show_libraries = False
        self._selected: Path | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-root"):
            yield Label("Pick a model", classes="title")
            yield Static(
                "OpenSCAD models under the current root (libraries — "
                "[italic]modules/[/], [italic]module_*[/], [italic]functions_*[/], "
                "[italic]*_constants.scad[/] — are hidden by default). "
                "Press [b]u[/] to go up one directory.",
                classes="help",
            )
            with Horizontal(classes="root-row"):
                yield Static(self._root_display(), id="current-root")
                yield Button("↑ parent", id="up-dir", disabled=self._at_filesystem_root())
            yield ScadModelTree(self._root, id="file-list")
            with Horizontal(classes="toggle-row"):
                yield Switch(value=False, id="show-libs")
                yield Label("Show libraries")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Pick", id="pick", variant="primary")

    def on_mount(self) -> None:
        tree = self.query_one("#file-list", ScadModelTree)
        tree.focus()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "show-libs":
            self._show_libraries = event.value
            tree = self.query_one("#file-list", ScadModelTree)
            tree.show_libraries = event.value

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        path = Path(str(event.path))
        if path.suffix == ".scad" and not is_preset_file(path):
            self.dismiss(path.resolve())

    def on_directory_tree_node_highlighted(
        self,
        event: DirectoryTree.NodeHighlighted[Any],
    ) -> None:
        # Track highlight so the "Pick" button works without a click.
        node = event.node
        if node.data is None:
            self._selected = None
            return
        try:
            path = Path(str(node.data.path))
        except AttributeError:
            self._selected = None
            return
        if path.is_file() and path.suffix == ".scad" and not is_preset_file(path):
            self._selected = path.resolve()
        else:
            self._selected = None

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "up-dir":
            await self.action_go_up()
        elif event.button.id == "pick" and self._selected is not None:
            self.dismiss(self._selected)

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def action_go_up(self) -> None:
        if self._at_filesystem_root():
            return
        await self._reroot(self._root.parent)

    # --- Internal ----------------------------------------------------------

    def _at_filesystem_root(self) -> bool:
        return self._root.parent == self._root

    def _root_display(self) -> str:
        return f"Root: [b]{self._root}[/]"

    async def _reroot(self, new_root: Path) -> None:
        new_root = new_root.resolve()
        if new_root == self._root:
            return
        self._root = new_root
        self._selected = None
        # DirectoryTree doesn't support live re-rooting reliably across
        # versions, so swap the widget out. Await the removal so the id
        # frees up before we mount the replacement.
        await self.query_one("#file-list", ScadModelTree).remove()
        new_tree = ScadModelTree(
            self._root,
            show_libraries=self._show_libraries,
            id="file-list",
        )
        container = self.query_one("#picker-root", Vertical)
        await container.mount(new_tree, before=container.query_one(".toggle-row"))
        new_tree.focus()
        self.query_one("#current-root", Static).update(self._root_display())
        self.query_one("#up-dir", Button).disabled = self._at_filesystem_root()
