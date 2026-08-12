# Environment setup with `uv`

This guide sets up a local Python environment for `noid-collections` using
[`uv`](https://docs.astral.sh/uv/) and shows how to run a scene with
`noid-play`.

`noid-collections` is a **companion package** to the
[`noid`](../../noid) framework — `noid` provides the component runtime
(`Bus`, `OidComponent`, `NoidPlayer`), and `noid-collections` provides the
reusable component implementations (`data:*`, `basic:*`, `lm:*`, `logic:*`,
`pdf:*`). You need both checked out as sibling directories:

```
~/git/mundorum/
  noid/              # framework — provides noid-play
  noid-collections/  # this project — components + scenes
```

## 1. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Confirm it's on your `PATH`:

```bash
uv --version
```

## 2. Create the virtual environment

From the `noid-collections` project root:

```bash
cd ~/git/mundorum/noid-collections
uv venv --python 3.10
```

`pyproject.toml` requires `requires-python = ">=3.10"`; any interpreter `uv`
can find that satisfies this works (drop `--python 3.10` to let `uv` pick
its default).

Activate it (only needed for interactive shell use — `uv run` below doesn't
require activation):

```bash
source .venv/bin/activate
```

## 3. Install the framework and component dependencies

The framework (`mundorum-noid`) is the only hard dependency; every
component's extra library (Ollama client, DuckDB, transformers, etc.) is an
**optional extra**, since most scenes only use a handful of components.

Editable-install the sibling `noid` framework first, then this project with
the extras you need:

```bash
uv pip install -e ../noid
uv pip install -e ".[dev]"          # core + pytest, no component extras
```

Add extras as needed, comma-separated, matching the component groups
declared in [`pyproject.toml`](../pyproject.toml):

```bash
uv pip install -e ".[lm]"           # slm:llm-agent (Ollama)
uv pip install -e ".[sql]"          # data:sql (DuckDB backend)
uv pip install -e ".[prolog]"       # logic:prolog (requires SWI-Prolog on the system)
uv pip install -e ".[pdf]"          # pdf:* pipeline (requires Ghostscript + Tesseract for OCR)
uv pip install -e ".[ner]"          # lm:ner (HuggingFace transformers + torch — heavy)
uv pip install -e ".[slm]"          # shorthand for lm + ner
uv pip install -e ".[all]"          # every extra
```

You can combine extras in one call, e.g. `uv pip install -e ".[lm,sql,dev]"`.

Components with system-level dependencies (SWI-Prolog for `logic:prolog`;
Ghostscript and Tesseract for `pdf:ocr`) still need those installed via your
OS package manager — the Python extra only installs the Python bindings.

## 4. Run a scene

Scenes are JSON files describing which components to wire together (see
[`~/git/mundorum/noid/docs/player.md`](../../noid/docs/player.md)). Run one
with the `noid-play` console script that `mundorum-noid` installs:

```bash
uv run noid-play playground/learning/02-data/copy_text/scene.json
```

Useful flags:

```bash
uv run noid-play scenes/slm_demo.json --timeout 30   # stop after N seconds
uv run noid-play scenes/slm_demo.json --verbose       # print bus traffic
```

`uv run` executes the command inside the project's `.venv` without requiring
you to `source .venv/bin/activate` first — convenient for one-off runs and
scripts.

Component `type` values in scene JSON use the `noid:` namespace defined in
[`noid-namespaces.yaml`](../noid-namespaces.yaml), which maps to the
`noid_collections` package — no extra configuration needed as long as you
run `noid-play` from within (or below) the project root.

## 5. Run the tests

```bash
uv run pytest
```

This requires the `dev` extra installed (step 3) for `pytest` /
`pytest-asyncio`.

## Quick reference

| Task                          | Command                                     |
| ----------------------------- | ------------------------------------------- |
| Create venv                   | `uv venv --python 3.10`                   |
| Install framework (editable)  | `uv pip install -e ../noid`               |
| Install this project + extras | `uv pip install -e ".[lm,sql,dev]"`       |
| Run a scene                   | `uv run noid-play <scene.json>`           |
| Run a scene with bus logging  | `uv run noid-play <scene.json> --verbose` |
| Run tests                     | `uv run pytest`                           |
