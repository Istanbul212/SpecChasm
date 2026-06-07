# Atalanta

Atalanta is an MVP for probing gaps in Lean-backed formal specifications
with generated mutation testing.

## Overview

Atalanta takes a small structured JSON spec, derives a Lean model and theorem
set from that spec, generates generic mutants from the model, and asks Lean
whether each mutated model still satisfies the same properties.

If Lean accepts a mutant, the written properties did not rule out that wrong
model. The tool reports the survivor and sketches the kind of property that
would distinguish it.

The current MVP supports:

- `Nat` and `Bool` state fields.
- Ordered `when` / `then` decision rules.
- Properties of the form `when [...] expect command = Output` or
  `command != Output`.
- Generated mutation operators for comparator flips, threshold shifts,
  dropped conditions, changed outputs, deleted rules, and unexpected outputs.

## Getting Started

Run the full web app with Lean-backed analysis:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 server.py
```

Then open http://127.0.0.1:8000.

The browser sends the spec text directly to the server, so there is no file upload step.
Generated Lean is checked through Lean's stdin mode and returned to the browser; normal web analysis does not write generated Lean files.

You can still open `web/index.html` directly, but direct-file mode uses a browser-only preview because it cannot run Lean.

If `lean` is not on your `PATH`, Atalanta will also try `~/.elan/bin/lean`.

## Spec Format

```json
{
  "name": "Example system",
  "state": {
    "temperature": "Nat",
    "sensor_valid": "Bool"
  },
  "outputs": ["On", "Off", "Fault"],
  "model": [
    {
      "when": ["sensor_valid = false"],
      "then": "Fault"
    },
    {
      "when": ["temperature > 100"],
      "then": "On"
    }
  ],
  "default": "Off",
  "properties": [
    {
      "id": "P1",
      "when": ["sensor_valid = false"],
      "expect": "command = Fault"
    }
  ]
}
```

## Development

Atalanta uses the Python standard library plus a local Lean executable.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest
```

## Deploying To Render

This repo includes a `render.yaml` blueprint for a Render web service.

1. Push the repo to GitHub.
2. In Render, choose **New > Blueprint**.
3. Select this repo.
4. Render will install Lean with `elan`, then start the Python web server.

The deployed service uses:

```sh
ELAN_HOME=$PWD/.elan python3 server.py --host 0.0.0.0
```

Render provides the `PORT` environment variable automatically, and `server.py`
uses it when present. The health check endpoint is `/api/health`.

For a manual Render web service, use:

```sh
export ELAN_HOME="$PWD/.elan"
curl -sSf https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain leanprover/lean4:v4.30.0
python3 -m compileall atalanta.py server.py
```

as the build command, and:

```sh
ELAN_HOME=$PWD/.elan python3 server.py --host 0.0.0.0
```

as the start command.

## Python API

```python
import json

import atalanta

with open("examples/eccs_initial_spec.json", encoding="utf-8") as spec_file:
    spec_data = json.load(spec_file)

spec = atalanta.Spec.from_data(spec_data, "examples/eccs_initial_spec.json")
analysis = atalanta.analyze_spec_data(spec, "examples/eccs_initial_spec.json")
payload = analysis.to_json()
```

For web requests, `server.py` accepts the spec JSON body directly at
`POST /api/analyze` and returns the generated Lean plus the analysis payload.
