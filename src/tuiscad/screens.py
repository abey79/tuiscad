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

    Shows every `.scad` file under the search directory (recursively),
    excluding tuiscad presets. Library files (those that look like
    dependencies based on path/filename heuristics) are hidden by default;
    a toggle reveals them.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
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
        self._selected: Path | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Pick a model", classes="title")
            yield Static(
                f"OpenSCAD models under [b]{self.search_dir}[/]. "
                "Libraries (modules/, [italic]module_*[/], [italic]functions_*[/]) "
                "are hidden by default.",
                classes="help",
            )
            yield ScadModelTree(self.search_dir, id="file-list")
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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "pick" and self._selected is not None:
            self.dismiss(self._selected)

    def action_cancel(self) -> None:
        self.dismiss(None)
