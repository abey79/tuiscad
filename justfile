set shell := ["bash", "-uc"]

# Default: show recipes.
default:
    @just --list

# Open the TUI for a .scad file. Presets are read/written in cwd.
tui FILE:
    uv run tuiscad {{FILE}}

# Render a preset to STL.
render PRESET OUT="":
    uv run python -c "import sys, subprocess, os, shutil, pathlib; \
        binary = os.environ.get('OPENSCAD_BIN') or shutil.which('openscad') or '/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD'; \
        out = '{{OUT}}' or pathlib.Path('{{PRESET}}').with_suffix('.stl'); \
        sys.exit(subprocess.call([binary, '-o', str(out), '{{PRESET}}']))"

# Run all tests.
test:
    uv run pytest

# Update snapshot baselines after intentional UI changes.
snapshot-update:
    uv run pytest --snapshot-update

# Lint + format check.
check:
    uv run ruff check .
    uv run ruff format --check .

# Auto-fix lint + format.
fix:
    uv run ruff check --fix .
    uv run ruff format .

# Type check.
typecheck:
    uv run mypy src
