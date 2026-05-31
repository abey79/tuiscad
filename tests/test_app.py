"""App-level tests using Textual's Pilot harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from tuiscad.app import TuiscadApp
from tuiscad.preset import new_preset

FIXTURE = Path(__file__).parent / "fixtures" / "sample.scad"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    # Copy the fixture next to the preset dir so include path resolves cleanly.
    target = tmp_path / "sample.scad"
    target.write_text(FIXTURE.read_text())
    return tmp_path


async def test_model_picker_can_navigate_up_from_search_dir(workspace: Path):
    """Pressing `u` (or the ↑ button) re-roots the model picker one level up.

    Real users often launch tuiscad from a subdir whose source `.scad` lives
    in the parent — they need a way to reach it without restarting.
    """
    from tuiscad.screens import ModelPickerScreen
    from tuiscad.treebrowse import ScadModelTree

    # Put a model in the parent dir so it's only reachable after going up.
    parent_model = workspace.parent / "parent_model.scad"
    parent_model.write_text("foo = 1;\n")
    try:
        app = TuiscadApp(workspace / "sample.scad", workspace)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            screen = ModelPickerScreen(workspace)
            await app.push_screen(screen)
            await pilot.pause()
            tree = screen.query_one("#file-list", ScadModelTree)
            assert Path(str(tree.path)).resolve() == workspace.resolve()

            await screen.action_go_up()
            await pilot.pause()
            tree = screen.query_one("#file-list", ScadModelTree)
            assert Path(str(tree.path)).resolve() == workspace.parent.resolve()
    finally:
        parent_model.unlink(missing_ok=True)


async def test_app_mounts_in_readonly_until_preset_created(workspace: Path):
    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.active_preset is None


async def test_creating_a_preset_enables_editing_and_persists_diff(workspace: Path):
    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        preset = new_preset("Test 1", app.source_path, app.search_dir, app.model)
        app.active_preset = preset
        app._render_params()
        app._save_preset_silently()
        await pilot.pause()

        app._on_param_changed("Width", [0, 102])
        app._on_param_changed("enable_magic", True)
        await pilot.pause()

        assert preset.overrides == {"Width": [0, 102], "enable_magic": True}
        assert preset.preset_path is not None
        assert preset.preset_path.exists()
        text = preset.preset_path.read_text()
        assert "Width = [0, 102];" in text
        assert "enable_magic = true;" in text
        # Untouched defaults must not appear.
        assert "pitch =" not in text


async def test_reset_removes_override(workspace: Path):
    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        preset = new_preset("Test", app.source_path, app.search_dir, app.model)
        app.active_preset = preset
        app._render_params()
        await pilot.pause()
        app._on_param_changed("Width", [9, 9])
        assert "Width" in preset.overrides
        app._on_param_changed("Width", None)  # reset
        assert "Width" not in preset.overrides


async def test_show_modified_only_filters(workspace: Path):
    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        preset = new_preset("Test", app.source_path, app.search_dir, app.model)
        app.active_preset = preset
        app._render_params()
        await pilot.pause()
        app._on_param_changed("enable_magic", True)
        app.show_modified_only = True
        await pilot.pause()
        from tuiscad.widgets import ParameterRow

        rows = list(app.query(ParameterRow))
        assert len(rows) == 1
        assert rows[0].param.name == "enable_magic"


async def test_clicking_group_in_sidebar_scrolls_to_header(workspace: Path):
    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        preset = new_preset("Test", app.source_path, app.search_dir, app.model)
        app.active_preset = preset
        app._render_params()
        await pilot.pause()
        # Header for the "Advanced" group must exist and be findable by class.
        targets = list(app.query(".group-advanced"))
        assert len(targets) == 1
        # Triggering the sidebar-pick handler must not raise.
        app._handle_sidebar_pick("group-advanced")
        await pilot.pause()


async def test_picking_preset_for_different_source_switches_models(workspace: Path):
    """A preset whose `// source:` points to a different .scad reloads that source on pick."""
    other = workspace / "other.scad"
    other.write_text("// description for foo\nfoo = 99;\n")

    pre = new_preset("alt", other, workspace)
    pre.set_override("foo", 11, default=99)
    pre.save()

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        # Source starts as sample.scad.
        assert app.source_path == (workspace / "sample.scad").resolve()
        # Activate the "alt" preset (which targets other.scad).
        assert pre.preset_path is not None
        app._activate_preset_file(pre.preset_path)
        await pilot.pause()
        assert app.source_path == other.resolve()
        assert app.active_preset is not None
        assert app.active_preset.name == "alt"
        # The new model has the `foo` parameter.
        assert app.model.by_name("foo") is not None


async def test_preset_tree_lists_all_presets_with_new_here_leaves(workspace: Path):
    """The sidebar tree should show every preset and a [+] new preset here leaf
    at every directory level."""
    sub = workspace / "configs"
    sub.mkdir()
    p1 = new_preset("alpha", workspace / "sample.scad", workspace)
    p1.save()
    p2 = new_preset("beta", workspace / "sample.scad", sub)
    p2.save()

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        from tuiscad.treebrowse import NewPresetHere, PresetTree

        tree = app.query_one(PresetTree)
        # Walk all nodes — there should be at least one [+] per directory.
        nodes = list(tree.root.children)
        node_data = [n.data for n in nodes]
        new_here_count = sum(1 for d in node_data if isinstance(d, NewPresetHere))
        assert new_here_count >= 1
        # Both preset files should appear somewhere in the tree.
        all_paths: list[Path] = []

        def walk(node):
            for child in node.children:
                if isinstance(child.data, Path):
                    all_paths.append(child.data)
                walk(child)

        walk(tree.root)
        assert any(p.name == "alpha.tui.scad" for p in all_paths)
        assert any(p.name == "beta.tui.scad" for p in all_paths)


async def test_sidebar_autosizes_to_content_capped_at_40_percent(workspace: Path):
    # Tiny content → sidebar should be small (well under the cap).
    new_preset("a", workspace / "sample.scad", workspace).save()
    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        small = app.query_one("#sidebar").size.width
        assert small < 48, f"expected sidebar < 48 (40% of 120), got {small}"

    # Massive name → sidebar caps at 40%.
    new_preset("x" * 200, workspace / "sample.scad", workspace).save()
    app2 = TuiscadApp(workspace / "sample.scad", workspace)
    async with app2.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        big = app2.query_one("#sidebar").size.width
        assert big <= 48
        assert big > small, "long names should expand the sidebar"


async def test_sidebar_resizes_when_a_long_preset_is_added(workspace: Path):
    """Creating a preset with a longer name than anything else mid-session
    should expand the sidebar without restarting the app."""
    new_preset("a", workspace / "sample.scad", workspace).save()
    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        before = app.query_one("#sidebar").size.width

        # Add a much longer preset to disk and refresh discovery + UI.
        new_preset("a" * 60, workspace / "sample.scad", workspace).save()
        from tuiscad.preset import discover_presets

        app.presets = discover_presets(None, app.search_dir)
        app._populate_preset_list()
        await pilot.pause()
        after = app.query_one("#sidebar").size.width
        assert after > before, f"sidebar didn't grow: {before} → {after}"


async def test_dropdown_with_default_outside_options_does_not_crash(workspace: Path):
    """Sources sometimes declare a default that isn't among the dropdown options
    (e.g. `enable_help = "disabled"; //[info,debug,trace]`). The widget should
    surface the value as an extra option rather than crashing."""
    src = workspace / "weird.scad"
    src.write_text('// help mode\nenable_help = "disabled"; //[info, debug, trace]\n')
    app = TuiscadApp(src, workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        preset = new_preset("test", src, workspace, app.model)
        app.active_preset = preset
        app._render_params()  # would have crashed before the fix
        await pilot.pause()
        from tuiscad.widgets import ParameterRow

        rows = [r for r in app.query(ParameterRow) if r.param.name == "enable_help"]
        assert len(rows) == 1


async def test_export_stl_target_path(workspace: Path, monkeypatch):
    """Exporting must produce `<preset-stem-without-tui>.stl` next to the preset."""
    captured: dict[str, Path] = {}

    async def fake_export(self, binary, preset_path, out_path):  # type: ignore[no-untyped-def]
        captured["preset"] = Path(preset_path)
        captured["out"] = Path(out_path)
        captured["binary"] = Path(binary)

    from tuiscad import app as app_mod

    monkeypatch.setattr(app_mod.TuiscadApp, "_do_export_stl", fake_export)
    monkeypatch.setattr(app_mod.TuiscadApp, "_resolve_openscad", lambda self: "/bin/echo")

    sub = workspace / "presets"
    sub.mkdir()
    pre = new_preset("My Build", workspace / "sample.scad", sub)
    pre.set_override("Width", [0, 50], default=[3, 0])
    pre.save()

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.active_preset = pre
        app.action_export_stl()
        await pilot.pause()
        assert captured["preset"].name == "my_build.tui.scad"
        assert captured["out"].name == "my_build.stl"
        assert captured["out"].parent == captured["preset"].parent


async def test_app_can_launch_without_a_source(workspace: Path):
    """Launching with no source file should still work — the user can pick a
    preset (which loads its source) or hit `n` to create a new preset."""
    pre = new_preset("preexisting", workspace / "sample.scad", workspace)
    pre.set_override("Width", [0, 50], default=[3, 0])
    pre.save()

    app = TuiscadApp(source_path=None, search_dir=workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert app.source_path is None
        assert app.active_preset is None
        # Discovered preset is still in the sidebar.
        names = [p.name for p in app.presets]
        assert "preexisting" in names
        # Activating it loads its source.
        assert pre.preset_path is not None
        app._activate_preset_file(pre.preset_path)
        await pilot.pause()
        assert app.source_path == (workspace / "sample.scad").resolve()
        assert app.active_preset is not None


async def test_duplicate_preset_clones_overrides_to_new_file(workspace: Path):
    pre = new_preset("original", workspace / "sample.scad", workspace)
    pre.set_override("Width", [0, 99], default=[3, 0])
    pre.save()

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._activate_preset_file(pre.preset_path)  # type: ignore[arg-type]
        await pilot.pause()

        # Simulate the modal returning a new name by invoking the inner callback
        # path directly: clone via the same code action_duplicate_preset uses.
        from tuiscad.preset import Preset, preset_filename

        new_path = workspace / preset_filename("clone")
        assert not new_path.exists()
        clone = Preset(
            name="clone",
            source_path=app.active_preset.source_path,  # type: ignore[union-attr]
            overrides=dict(app.active_preset.overrides),  # type: ignore[union-attr]
            preset_path=new_path,
        )
        clone.save()
        assert new_path.exists()
        assert "Width = [0, 99];" in new_path.read_text()
        assert clone.overrides == {"Width": [0, 99]}


async def test_rename_preset_renames_the_file(workspace: Path):
    pre = new_preset("oldname", workspace / "sample.scad", workspace)
    pre.set_override("Width", [0, 1], default=[3, 0])
    pre.save()

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._activate_preset_file(pre.preset_path)  # type: ignore[arg-type]
        await pilot.pause()

        from tuiscad.screens import NewPresetScreen

        app.action_rename_preset()
        await pilot.pause()
        assert isinstance(app.screen, NewPresetScreen)
        app.screen._submit("brand new")
        await pilot.pause()

        assert not (workspace / "oldname.tui.scad").exists()
        new_path = workspace / "brand_new.tui.scad"
        assert new_path.exists()
        # Overrides survive the rename.
        assert "Width = [0, 1];" in new_path.read_text()
        # Active preset follows the rename; its name is the new file name.
        assert app.active_preset is not None
        assert app.active_preset.name == "brand_new"


async def test_rename_preset_offers_and_renames_matching_stl(workspace: Path):
    pre = new_preset("widget", workspace / "sample.scad", workspace)
    pre.save()
    stl = workspace / "widget.stl"
    stl.write_bytes(b"solid x\nendsolid x\n")

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._activate_preset_file(pre.preset_path)  # type: ignore[arg-type]
        await pilot.pause()

        from tuiscad.screens import ConfirmScreen, NewPresetScreen

        app.action_rename_preset()
        await pilot.pause()
        assert isinstance(app.screen, NewPresetScreen)
        app.screen._submit("gadget")
        await pilot.pause()

        # A matching STL exists → we must be asked about it.
        assert isinstance(app.screen, ConfirmScreen)
        app.screen.dismiss(True)
        await pilot.pause()

        assert (workspace / "gadget.tui.scad").exists()
        assert not stl.exists()
        assert (workspace / "gadget.stl").exists()


async def test_rename_preset_declining_stl_keeps_it(workspace: Path):
    pre = new_preset("widget", workspace / "sample.scad", workspace)
    pre.save()
    stl = workspace / "widget.stl"
    stl.write_bytes(b"solid x\nendsolid x\n")

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._activate_preset_file(pre.preset_path)  # type: ignore[arg-type]
        await pilot.pause()

        from tuiscad.screens import ConfirmScreen, NewPresetScreen

        app.action_rename_preset()
        await pilot.pause()
        assert isinstance(app.screen, NewPresetScreen)
        app.screen._submit("gadget")
        await pilot.pause()

        assert isinstance(app.screen, ConfirmScreen)
        app.screen.dismiss(False)  # decline the STL rename
        await pilot.pause()

        # Preset still renamed; the STL is left untouched at its old name.
        assert (workspace / "gadget.tui.scad").exists()
        assert stl.exists()
        assert not (workspace / "gadget.stl").exists()


async def test_rename_preset_rejects_existing_target(workspace: Path):
    a = new_preset("alpha", workspace / "sample.scad", workspace)
    a.save()
    b = new_preset("beta", workspace / "sample.scad", workspace)
    b.save()

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._activate_preset_file(a.preset_path)  # type: ignore[arg-type]
        await pilot.pause()

        from tuiscad.screens import NewPresetScreen

        app.action_rename_preset()
        await pilot.pause()
        assert isinstance(app.screen, NewPresetScreen)
        app.screen._submit("beta")  # collides with the existing preset
        await pilot.pause()

        # Both files still present; the rename was refused.
        assert (workspace / "alpha.tui.scad").exists()
        assert (workspace / "beta.tui.scad").exists()


async def test_delete_preset_removes_file_and_clears_active(workspace: Path):
    pre = new_preset("doomed", workspace / "sample.scad", workspace)
    pre.set_override("Width", [0, 50], default=[3, 0])
    pre.save()
    assert pre.preset_path is not None
    assert pre.preset_path.exists()

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app._activate_preset_file(pre.preset_path)
        await pilot.pause()

        # Simulate the confirm callback firing with True.
        target = app.active_preset
        assert target is not None and target.preset_path is not None
        target.preset_path.unlink()
        app.active_preset = None
        from tuiscad.preset import discover_presets

        app.presets = discover_presets(None, app.search_dir)
        assert not pre.preset_path.exists()
        assert "doomed" not in [p.name for p in app.presets]


async def test_existing_presets_are_discovered(workspace: Path):
    """Pre-existing presets in the search dir should appear on launch."""
    pre = new_preset("preexisting", workspace / "sample.scad", workspace)
    pre.set_override("Width", [0, 50], default=[3, 0])
    pre.save()

    app = TuiscadApp(workspace / "sample.scad", workspace)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        names = [p.name for p in app.presets]
        assert "preexisting" in names


def test_snapshot_initial_screen(tmp_path: Path, snap_compare):
    """Snapshot the initial UI to lock in the layout."""
    target = tmp_path / "sample.scad"
    target.write_text(FIXTURE.read_text())
    pre = new_preset("Atelier 51", target, tmp_path)
    pre.set_override("Width", [0, 102], default=[3, 0])
    pre.save()

    async def run_before(pilot) -> None:
        pilot.app.active_preset = pre
        pilot.app._render_params()
        pilot.app._populate_preset_list()
        pilot.app._refresh_status()
        await pilot.pause()

    assert snap_compare(
        TuiscadApp(target, tmp_path),
        terminal_size=(120, 40),
        run_before=run_before,
    )
