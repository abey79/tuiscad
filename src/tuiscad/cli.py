"""Command-line entry point for tuiscad."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from .app import TuiscadApp


@click.command()
@click.argument(
    "scad_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=False,
)
@click.option(
    "--preset-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to read/write preset files (defaults to cwd).",
)
def main(scad_file: Path | None, preset_dir: Path | None) -> None:
    """Edit OpenSCAD customizer parameters as a TUI; save diffs as runnable presets.

    SCAD_FILE is optional. When omitted, tuiscad opens in browser mode:
    pick a preset from the sidebar (its source loads automatically), or
    press [n] to create a new preset and choose a model.
    """
    if preset_dir is None:
        preset_dir = Path.cwd()
    preset_dir.mkdir(parents=True, exist_ok=True)
    app = TuiscadApp(source_path=scad_file, search_dir=preset_dir)
    app.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
