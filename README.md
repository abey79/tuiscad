# tuiscad

A terminal UI for the OpenSCAD customizer. Tweak parameters as text, save the
**diff** as a runnable `.scad` preset, and let OpenSCAD's auto-reload preview
the result live.

## Why

The built-in OpenSCAD customizer stores presets as opaque JSON, persists the
*entire* parameter set, and lives inside the GUI. tuiscad takes the opposite
posture:

- **Diff-only presets.** Each preset records *only* the variables you've changed.
  Source defaults stay in the source.
- **Runnable presets.** A preset is a real `.scad` file (`<slug>.tui.scad`):
  ```scad
  // tuiscad-preset
  // name: drawers atelier 51x51 v2
  // source: gridfinity_baseplate.scad

  include <gridfinity_baseplate.scad>

  // === overrides ===
  pitch = [51, 51, 7];
  Width = [0, 102];
  ```
  OpenSCAD's "last assignment wins" makes the overrides take effect. Run with
  `openscad <preset>.tui.scad` — no preset selector needed.
- **Named-first.** A preset must be created and named before any edit lands;
  the UI is read-only until then so changes can never go to an anonymous bucket.
- **Visible delta.** Modified parameters are highlighted; toggle "modified
  only" to see just your diff. Per-parameter reset restores the default.
- **Live preview.** Open the preset in OpenSCAD with `o`; OpenSCAD auto-reload
  re-renders on every save (auto-save fires on every edit).

## Install

You'll need [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv tool install git+https://github.com/abey79/tuiscad.git
```

This puts the `tuiscad` command on your `PATH`. To upgrade later: `uv tool upgrade tuiscad`.

### Local checkout (recommended if you want to hack on it — LLMs are quite good at extending small Textual apps like this one)

```sh
git clone https://github.com/abey79/tuiscad.git
cd tuiscad
uv tool install -e .
```

## Usage

```sh
tuiscad path/to/your.scad
# or, from a local checkout:
just tui path/to/your.scad
```

Bindings:

| Key      | Action                                   |
| -------- | ---------------------------------------- |
| `n`      | New preset (must be named)               |
| `m`      | Toggle "modified only" filter            |
| `o`      | Open the active preset in OpenSCAD       |
| `e`      | Export the active preset to STL          |
| `d`      | Duplicate the active preset              |
| `Delete` | Delete the active preset (with confirm)  |
| `Ctrl+S` | Save (auto-save is on, but explicit too) |
| `Ctrl+Q` | Quit                                     |

Presets are written to the current directory as `<slug>.tui.scad`. The
binding to a source `.scad` lives inside the preset's `// source:` metadata
header (and matching `include <...>`), not in the filename.

Creating a new preset opens a model picker that lists every `.scad` under the
current directory recursively. Library files (paths matching `*/modules/*`,
filenames starting with `module_*` / `functions_*` / `function_*`, or ending
in `_constants.scad`) are hidden by default; toggle "Show libraries" to
include them.

The preset sidebar shows *all* presets in the directory regardless of which
model they target — picking a preset for a different model auto-switches the
loaded source.

## Bake an STL

Press `e` inside the TUI, or from the shell:

```sh
just render atelier_51.tui.scad
# → atelier_51.stl
```

The OpenSCAD binary is resolved from `$OPENSCAD_BIN`, then `$PATH`, then
`/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD`.

## Tests

```sh
just test            # run all tests
just snapshot-update # update Textual snapshot baselines after intentional UI changes
just check           # ruff lint + format check
```

## Layout

```
src/tuiscad/
  parser.py    — parses customizer params (groups, hints, dropdowns, ranges)
  models.py    — Parameter / Hint / ScadModel dataclasses
  preset.py    — Preset model: load / save / diff
  widgets.py   — ParameterRow + value-type-specific editors
  screens.py   — modal screens (NewPreset)
  app.py       — TuiscadApp (the Textual application)
  cli.py       — `tuiscad <file>` entry point
tests/
  test_parser.py / test_preset.py / test_app.py
  fixtures/sample.scad
```
