"""Preset model tests."""

from __future__ import annotations

from pathlib import Path

from tuiscad.preset import (
    Preset,
    discover_presets,
    format_scad_value,
    load_preset,
    new_preset,
    preset_filename,
    slugify,
    values_equal,
)


def test_slugify_handles_spaces_and_special_chars():
    assert slugify("Drawers Atelier 51x51 v2") == "drawers_atelier_51x51_v2"
    assert slugify("  hello!! world  ") == "hello_world"
    assert slugify("") == "preset"


def test_format_scad_value_roundtrip():
    assert format_scad_value(True) == "true"
    assert format_scad_value(False) == "false"
    assert format_scad_value(42) == "42"
    assert format_scad_value(3.14) == "3.14"
    assert format_scad_value(1.0) == "1"
    assert format_scad_value("hi") == '"hi"'
    assert format_scad_value([1, 2, 3]) == "[1, 2, 3]"
    assert format_scad_value([1, [2, 3]]) == "[1, [2, 3]]"


def test_values_equal_numeric_promotion():
    assert values_equal(1, 1.0)
    assert values_equal([1, 2], [1.0, 2.0])
    assert not values_equal([1, 2], [1, 3])
    assert not values_equal(True, 1)  # bool is special-cased


def test_set_override_drops_when_matching_default():
    p = Preset(name="x", source_path=Path("src.scad"))
    p.set_override("a", 5, default=1)
    assert p.overrides == {"a": 5}
    p.set_override("a", 1, default=1)
    assert p.overrides == {}


def test_save_and_load_roundtrip(tmp_path: Path):
    src = Path("source.scad")
    p = Preset(name="atelier 51", source_path=src)
    p.set_override("pitch", [51, 51, 7], default=[42, 42, 7])
    p.set_override("Enable_Magnets", True, default=False)
    target = tmp_path / preset_filename(p.name)
    p.save(target)

    loaded = load_preset(target)
    assert loaded.name == "atelier 51"
    assert loaded.source_path == Path("source.scad")
    assert loaded.overrides == {"pitch": [51, 51, 7], "Enable_Magnets": True}
    assert loaded.preset_path == target


def test_only_diff_is_persisted(tmp_path: Path):
    p = Preset(name="default", source_path=Path("source.scad"))
    p.set_override("a", 1, default=1)  # equals default → not stored
    p.set_override("b", 2, default=1)
    target = tmp_path / "default.tui.scad"
    p.save(target)
    text = target.read_text()
    assert "b = 2" in text
    assert "a = " not in text


def test_new_preset_path_uses_search_dir(tmp_path: Path):
    src = tmp_path / "source.scad"
    src.write_text("// dummy")
    p = new_preset("my profile", src, tmp_path)
    assert p.preset_path is not None
    assert p.preset_path.parent == tmp_path
    assert p.preset_path.name == "my_profile.tui.scad"


def test_new_preset_makes_include_relative_to_preset_dir(tmp_path: Path):
    """The preset's include path must resolve to the source file from the preset's directory."""
    sub = tmp_path / "sub"
    sub.mkdir()
    src = tmp_path / "source.scad"
    src.write_text("foo = 1;")
    p = new_preset("rel", src, sub)
    assert str(p.source_path) == "../source.scad"
    p.set_override("foo", 2, default=1)
    p.save()
    assert "include <../source.scad>" in p.preset_path.read_text()
    # And resolving the include from the preset's directory yields the source.
    assert (sub / p.source_path).resolve() == src.resolve()


def test_discover_presets_filters_by_resolved_source(tmp_path: Path):
    """Presets are matched by `// source:` resolving to the requested file,
    not by filename — the new naming has no source prefix."""
    source = tmp_path / "source.scad"
    source.write_text("foo = 1;")
    other = tmp_path / "other.scad"
    other.write_text("bar = 2;")

    new_preset("alpha", source, tmp_path).save()
    new_preset("beta", source, tmp_path).save()
    new_preset("gamma", other, tmp_path).save()

    matched = discover_presets(source, tmp_path)
    assert sorted(p.name for p in matched) == ["alpha", "beta"]

    # No filter → all presets.
    everything = discover_presets(None, tmp_path)
    assert sorted(p.name for p in everything) == ["alpha", "beta", "gamma"]


def test_discover_presets_recursive(tmp_path: Path):
    source = tmp_path / "source.scad"
    source.write_text("foo = 1;")
    sub = tmp_path / "nested" / "deeper"
    sub.mkdir(parents=True)
    new_preset("buried", source, sub).save()
    found = discover_presets(source, tmp_path)
    assert [p.name for p in found] == ["buried"]
