# Atalanta

Atalanta is a CLI MVP for probing gaps in Lean-backed formal specifications
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

You can still open `web/index.html` directly, but direct-file mode uses a browser-only preview because it cannot run Lean.

Run the initial spec demo:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 atalanta.py examples/eccs_initial_spec.json
```

Run the strengthened spec that kills all generated mutants:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 atalanta.py examples/eccs_strengthened_spec.json --strict
```

Keep generated Lean files for inspection:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 atalanta.py examples/eccs_initial_spec.json --keep-lean-dir /tmp/atalanta-lean
```

Emit JSON:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 atalanta.py examples/eccs_initial_spec.json --json
```

If `lean` is not on your `PATH`, Atalanta will also try `~/.elan/bin/lean`.
You can pass it explicitly:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 atalanta.py examples/eccs_initial_spec.json --lean-bin ~/.elan/bin/lean
```

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

## CLI Contract

```sh
python3 atalanta.py SPEC_FILE [--lean-bin LEAN] [--keep-lean-dir DIR] [--json] [--strict] [--show-lean-errors]
```

- `SPEC_FILE` is a structured JSON specification.
- `--lean-bin` points to the Lean executable when it is not discoverable.
- `--keep-lean-dir` preserves generated Lean files for inspection.
- `--json` emits stable machine-readable output.
- `--strict` exits with status `1` when the original model fails or any mutant survives.
- `--show-lean-errors` includes Lean failure excerpts for killed mutants.
