# SpecChasm

SpecChasm is an MVP for detecting gaps in Lean-backed formal specifications.

## Overview

SpecChasm takes a small structured JSON spec, derives a Lean model and theorem
set from that spec, generates generic mutants from the model, and asks Lean
whether each mutated model still satisfies the same properties.

For web performance, SpecChasm batches the original model and every generated
mutant into one Lean source and invokes Lean once per analysis request.

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
python3 server.py
```

Then open http://127.0.0.1:8000.

If `lean` is not on your `PATH`, SpecChasm will also try `~/.elan/bin/lean`.

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

SpecChasm uses the Python standard library plus a local Lean executable.

```sh
python3 -m unittest
```

## Deploying To Render

This repo includes a `render.yaml` blueprint for a Render web service.

## Python API

```python
import json

import specchasm

with open("examples/eccs_initial_spec.json", encoding="utf-8") as spec_file:
    spec_data = json.load(spec_file)

spec = specchasm.Spec.from_data(spec_data, "examples/eccs_initial_spec.json")
analysis = specchasm.analyze_spec_data(spec, "examples/eccs_initial_spec.json")
payload = analysis.to_json()
```

For web requests, `server.py` accepts the spec JSON body directly at
`POST /api/analyze` and returns the generated Lean plus the specchasm payload.
