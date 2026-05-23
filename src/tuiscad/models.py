"""Data model for parsed OpenSCAD parameters and presets."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

ScadValue = bool | int | float | str | list[Any]


class ParamKind(StrEnum):
    BOOL = "bool"
    NUMBER = "number"
    STRING = "string"
    VECTOR = "vector"
    DROPDOWN = "dropdown"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DropdownOption:
    value: ScadValue
    label: str


@dataclass(frozen=True)
class Hint:
    """Customizer widget hint parsed from a trailing `// ...` comment."""

    step: float | None = None
    min: float | None = None
    max: float | None = None
    options: tuple[DropdownOption, ...] | None = None
    raw: str = ""

    @property
    def is_range(self) -> bool:
        return self.min is not None and self.max is not None

    @property
    def is_dropdown(self) -> bool:
        return self.options is not None


@dataclass
class Parameter:
    name: str
    default: ScadValue
    kind: ParamKind
    raw_value: str
    description: str = ""
    group: str = ""
    hint: Hint | None = None
    line_no: int = 0

    @property
    def widget_kind(self) -> ParamKind:
        if self.hint and self.hint.is_dropdown:
            return ParamKind.DROPDOWN
        return self.kind


@dataclass
class ScadModel:
    source_path: Path
    parameters: list[Parameter] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)

    def by_name(self, name: str) -> Parameter | None:
        return next((p for p in self.parameters if p.name == name), None)

    def parameters_in_group(self, group: str) -> list[Parameter]:
        return [p for p in self.parameters if p.group == group]
