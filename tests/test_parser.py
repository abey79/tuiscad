"""Parser tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tuiscad.models import ParamKind
from tuiscad.parser import parse_scad, parse_source

FIXTURE = Path(__file__).parent / "fixtures" / "sample.scad"


@pytest.fixture
def model():
    return parse_scad(FIXTURE)


def test_stops_at_hidden_marker_and_module(model):
    names = [p.name for p in model.parameters]
    assert "secret" not in names
    assert "ignored" not in names


def test_extracts_basic_kinds(model):
    by_name = {p.name: p for p in model.parameters}

    assert by_name["Width"].kind == ParamKind.VECTOR
    assert by_name["Width"].default == [3, 0]
    assert by_name["Width"].hint is not None
    assert by_name["Width"].hint.step == 0.1

    assert by_name["enable_magic"].kind == ParamKind.BOOL
    assert by_name["enable_magic"].default is False

    assert by_name["mode"].kind == ParamKind.STRING
    assert by_name["mode"].hint is not None
    assert by_name["mode"].hint.options is not None
    assert {opt.value for opt in by_name["mode"].hint.options} == {"auto", "manual", "off"}


def test_labeled_dropdown_preserves_quoted_labels(model):
    pos = next(p for p in model.parameters if p.name == "position")
    assert pos.hint and pos.hint.options
    labels = {opt.value: opt.label for opt in pos.hint.options}
    assert labels == {"near": "← left", "center": "↔ center", "far": "→ right"}


def test_range_hint(model):
    by_name = {p.name: p for p in model.parameters}

    weight = by_name["weight"]
    assert weight.hint and weight.hint.is_range
    assert (weight.hint.min, weight.hint.step, weight.hint.max) == (0.0, 0.1, 10.0)

    items = by_name["items"]
    assert items.hint and items.hint.is_range
    assert (items.hint.min, items.hint.step, items.hint.max) == (1.0, 1.0, 10.0)


def test_descriptions_attach_to_following_variable(model):
    width = next(p for p in model.parameters if p.name == "Width")
    assert width.description == "X dimension. units or mm."


def test_groups_assigned(model):
    by_name = {p.name: p for p in model.parameters}
    assert by_name["pitch"].group == "Advanced"
    assert by_name["Width"].group == ""
    assert "Advanced" in model.groups


def test_nested_vectors_parse(model):
    xpos = next(p for p in model.parameters if p.name == "xpos1")
    assert xpos.kind == ParamKind.VECTOR
    assert xpos.default == [3, [2, [3, 3]], 0, 2, 4, 0]


def test_skip_special_dollar_variables():
    src = """
    foo = 1;
    $fa = 6;
    $fs = 0.1;
    bar = 2;
    """
    model = parse_source(src)
    names = [p.name for p in model.parameters]
    assert "foo" in names
    assert "bar" in names
    assert all(not n.startswith("$") for n in names)


def test_blank_line_breaks_description():
    src = """
    // not a description for foo

    foo = 1;
    """
    model = parse_source(src)
    foo = model.parameters[0]
    assert foo.name == "foo"
    assert foo.description == ""
