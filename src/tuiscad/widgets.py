"""Custom widgets that render a single :class:`Parameter` row."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Label, Select, Static, Switch

from .models import Parameter, ParamKind, ScadValue
from .preset import format_scad_value, values_equal

ValueChanged = Callable[[str, ScadValue | None], None]
"""Callback: (param_name, new_value).  `new_value=None` means "reset to default"."""


class ParameterRow(Vertical):
    """Renders one parameter: label, description, editor widget, modified marker."""

    DEFAULT_CSS = """
    ParameterRow {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
        border-left: tall $surface;
    }
    ParameterRow.-modified {
        border-left: tall $warning;
        background: $warning 10%;
    }
    ParameterRow .name {
        color: $text;
        text-style: bold;
        width: 1fr;
    }
    ParameterRow .desc {
        color: $text-muted;
        height: auto;
    }
    ParameterRow .hint {
        color: $text-muted;
        text-style: italic;
        height: auto;
    }
    ParameterRow .editor-row {
        height: auto;
        margin-top: 0;
    }
    ParameterRow Input.vec-elem {
        width: 12;
        margin-right: 1;
    }
    ParameterRow Input {
        width: 1fr;
    }
    ParameterRow Switch {
        width: auto;
    }
    ParameterRow Select {
        width: 1fr;
    }
    ParameterRow .editor-spacer {
        width: 1fr;
        height: 1;
    }
    ParameterRow Button.reset {
        margin-left: 1;
        min-width: 9;
        dock: right;
    }
    """

    def __init__(
        self,
        param: Parameter,
        current: ScadValue,
        on_change: ValueChanged,
        *,
        editable: bool = True,
        suffix: str = "",
    ) -> None:
        sfx = f"-{suffix}" if suffix else ""
        super().__init__(id=f"param-{param.name}{sfx}")
        self.param = param
        self.current = current
        self.on_change = on_change
        self.editable = editable
        self._sfx = sfx

    def _input_id(self) -> str:
        return f"input-{self.param.name}{self._sfx}"

    def _reset_id(self) -> str:
        return f"reset-{self.param.name}{self._sfx}"

    def on_mount(self) -> None:
        self._refresh_modified_class()

    def compose(self) -> ComposeResult:
        yield Label(self.param.name, classes="name")
        if self.param.description:
            yield Static(self.param.description, classes="desc")
        hint_str = _hint_summary(self.param)
        if hint_str:
            yield Static(hint_str, classes="hint")
        with Horizontal(classes="editor-row"):
            yield from self._build_editor()
            yield Button(
                "reset",
                classes="reset",
                disabled=not self._is_modified(),
                id=self._reset_id(),
            )

    # --- Editor builders ---------------------------------------------------

    def _build_editor(self) -> ComposeResult:
        kind = self.param.widget_kind
        if kind == ParamKind.DROPDOWN and self.param.hint and self.param.hint.options:
            # Select requires Hashable values; ScadValue includes list. We
            # guard with _is_hashable() at runtime, but the static type still
            # widens to include list — cast to Any to escape the SelectType
            # constraint.
            opts: list[tuple[str, Any]] = [
                (opt.label, opt.value) for opt in self.param.hint.options
            ]
            # Some sources declare a default that isn't among the dropdown
            # options (e.g. `enable_help = "disabled"; //[info,debug,trace]`).
            # Surface the current value as an extra option so we never have to
            # fall back to BLANK (which Textual rejects when allow_blank=False).
            if not any(self.current == v for _, v in opts) and _is_hashable(self.current):
                opts = [*opts, (f"{self.current} (custom)", self.current)]
            yield Select(
                options=opts,
                value=self.current if _is_hashable(self.current) else opts[0][1],
                allow_blank=True,
                disabled=not self.editable,
                id=self._input_id(),
            )
            return
        if self.param.kind == ParamKind.BOOL:
            yield Switch(
                value=bool(self.current),
                disabled=not self.editable,
                id=self._input_id(),
            )
            return
        if (
            self.param.kind == ParamKind.VECTOR
            and isinstance(self.current, list)
            and all(_is_scalar(elem) for elem in self.current)
        ):
            for i, elem in enumerate(self.current):
                yield Input(
                    value=format_scad_value(elem),
                    classes="vec-elem",
                    disabled=not self.editable,
                    id=f"{self._input_id()}-{i}",
                )
            return
        # Default: single text input (also handles nested vectors as raw text).
        yield Input(
            value=_format_value_as_text(self.current),
            disabled=not self.editable,
            id=self._input_id(),
        )

    # --- Event handlers ----------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if not event.input.id or not event.input.id.startswith(self._input_id()):
            return
        self._gather_and_emit()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id != self._input_id():
            return
        if values_equal(event.value, self.current):
            return
        self.current = event.value
        self.on_change(self.param.name, event.value)
        self._refresh_modified_class()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != self._input_id():
            return
        if event.value is Select.BLANK:
            return
        value = cast(ScadValue, event.value)
        if values_equal(value, self.current):
            return
        self.current = value
        self.on_change(self.param.name, value)
        self._refresh_modified_class()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != self._reset_id():
            return
        self.on_change(self.param.name, None)

    # --- Helpers -----------------------------------------------------------

    def _gather_and_emit(self) -> None:
        try:
            value = self._collect_input_value()
        except _ValidationError:
            return
        # Skip phantom changes (e.g. Input fires Changed on mount).
        if values_equal(value, self.current):
            return
        self.current = value
        self.on_change(self.param.name, value)
        self._refresh_modified_class()

    def _collect_input_value(self) -> ScadValue:
        if (
            self.param.kind == ParamKind.VECTOR
            and isinstance(self.current, list)
            and all(_is_scalar(elem) for elem in self.current)
        ):
            elems: list[ScadValue] = []
            base = self._input_id()
            for i, _ in enumerate(self.current):
                inp = self.query_one(f"#{base}-{i}", Input)
                elems.append(_parse_scalar(inp.value))
            return elems
        inp = self.query_one(f"#{self._input_id()}", Input)
        return _parse_text_value(inp.value)

    def _is_modified(self) -> bool:
        return not values_equal(self.current, self.param.default)

    def _refresh_modified_class(self) -> None:
        self.set_class(self._is_modified(), "-modified")
        try:
            btn = self.query_one(f"#{self._reset_id()}", Button)
            btn.disabled = not self._is_modified() or not self.editable
        except Exception:
            pass

    def update_current(self, current: ScadValue) -> None:
        """Called by the app when external changes (e.g. reset) update the value."""
        self.current = current
        self._reset_widgets_to_current()
        self._refresh_modified_class()

    def _reset_widgets_to_current(self) -> None:
        kind = self.param.widget_kind
        base = self._input_id()
        if kind == ParamKind.DROPDOWN:
            sel = self.query_one(f"#{base}", Select)
            with sel.prevent(Select.Changed):
                sel.value = cast(Any, self.current)
            return
        if self.param.kind == ParamKind.BOOL:
            sw = self.query_one(f"#{base}", Switch)
            with sw.prevent(Switch.Changed):
                sw.value = bool(self.current)
            return
        if (
            self.param.kind == ParamKind.VECTOR
            and isinstance(self.current, list)
            and all(_is_scalar(elem) for elem in self.current)
        ):
            for i, elem in enumerate(self.current):
                inp = self.query_one(f"#{base}-{i}", Input)
                with inp.prevent(Input.Changed):
                    inp.value = format_scad_value(elem)
            return
        inp = self.query_one(f"#{base}", Input)
        with inp.prevent(Input.Changed):
            inp.value = _format_value_as_text(self.current)


# --- Helpers --------------------------------------------------------------


class _ValidationError(Exception):
    pass


def _format_value_as_text(value: ScadValue) -> str:
    if isinstance(value, str):
        return value
    return format_scad_value(value)


def _is_scalar(value: ScadValue) -> bool:
    return isinstance(value, (bool, int, float, str))


def _is_hashable(value: object) -> bool:
    try:
        hash(value)
        return True
    except TypeError:
        return False


def _parse_scalar(text: str) -> ScadValue:
    text = text.strip()
    if text == "":
        raise _ValidationError("empty")
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        if "." in text or "e" in text.lower():
            return float(text)
        return int(text)
    except ValueError:
        return text


def _parse_text_value(text: str) -> ScadValue:
    """Parse a text-input value, recognizing list literals so nested vectors round-trip."""
    from .parser import _parse_value, _ParseError

    text = text.strip()
    if text == "":
        raise _ValidationError("empty")
    try:
        v, _ = _parse_value(text)
        return v
    except _ParseError:
        return _parse_scalar(text)


def _hint_summary(param: Parameter) -> str:
    parts: list[str] = []
    if param.kind != ParamKind.UNKNOWN:
        parts.append(param.kind.value)
    if param.hint:
        if param.hint.is_range:
            parts.append(f"range {param.hint.min}..{param.hint.max} step {param.hint.step}")
        elif param.hint.step is not None:
            parts.append(f"step {param.hint.step}")
        elif param.hint.is_dropdown and param.hint.options:
            parts.append(f"{len(param.hint.options)} choices")
    parts.append(f"default = {format_scad_value(param.default)}")
    return " · ".join(parts)
