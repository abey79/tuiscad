"""Discovery + library-heuristic tests."""

from __future__ import annotations

from pathlib import Path

from tuiscad.discovery import find_scad_files, is_library


def test_is_library_path_heuristics(tmp_path: Path):
    # /modules/ in the path → library
    assert is_library(tmp_path / "modules" / "thing.scad")
    assert is_library(tmp_path / "src" / "modules" / "thing.scad")
    # filename prefix → library
    assert is_library(tmp_path / "module_foo.scad")
    assert is_library(tmp_path / "functions_bar.scad")
    assert is_library(tmp_path / "function_bar.scad")
    # _constants.scad suffix → library
    assert is_library(tmp_path / "gridfinity_constants.scad")
    # ordinary names → not library
    assert not is_library(tmp_path / "gridfinity_baseplate.scad")
    assert not is_library(tmp_path / "my_part.scad")


def test_find_scad_files_excludes_presets_and_classifies(tmp_path: Path):
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "module_foo.scad").write_text("")
    (tmp_path / "module_top.scad").write_text("")
    (tmp_path / "gridfinity_baseplate.scad").write_text("")
    (tmp_path / "my_part.scad").write_text("")
    (tmp_path / "atelier.tui.scad").write_text("// tuiscad-preset\n// name: x\n// source: y.scad")

    files = find_scad_files(tmp_path)
    names = [str(f.display_path) for f in files]

    # Preset is excluded.
    assert "atelier.tui.scad" not in names
    # All discovered files have absolute paths.
    assert all(f.path.is_absolute() for f in files)
    # Models come before libraries; within each group, alphabetic.
    models = [f for f in files if not f.is_library]
    libs = [f for f in files if f.is_library]
    assert [str(m.display_path) for m in models] == [
        "gridfinity_baseplate.scad",
        "my_part.scad",
    ]
    # Library paths can be in either order depending on glob; just check membership.
    assert {str(lib.display_path) for lib in libs} == {
        "module_top.scad",
        "modules/module_foo.scad",
    }
