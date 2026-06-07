import json
import unittest
from pathlib import Path
from unittest import mock

import specchasm


ROOT = Path(__file__).resolve().parents[1]
INITIAL_SPEC = ROOT / "examples" / "eccs_initial_spec.json"


def load_initial_spec():
    return specchasm.Spec.from_data(json.loads(INITIAL_SPEC.read_text(encoding="utf-8")), "eccs_initial_spec")


def fake_check(ok=True, path="generated.lean"):
    return specchasm.LeanCheck(
        ok=ok,
        path=path,
        stdout="",
        stderr="" if ok else "lean theorem failed",
        returncode=0 if ok else 1,
    )


class SpecChasmLeanTests(unittest.TestCase):
    def test_loads_structured_spec(self):
        spec = load_initial_spec()

        self.assertEqual("ECCS demo", spec.name)
        self.assertEqual(specchasm.StateType.NAT, spec.state["core_temperature"])
        self.assertEqual(["Inject", "Inhibit", "Fault"], spec.outputs)
        self.assertEqual(4, len(spec.model))
        self.assertEqual(4, len(spec.properties))

    def test_generates_mutants_from_model_not_catalog(self):
        spec = load_initial_spec()
        mutants = specchasm.generate_mutants(spec)

        names = {mutant.name for mutant in mutants}
        self.assertIn("Comparator changed", names)
        self.assertIn("Threshold changed", names)
        self.assertIn("Condition dropped", names)
        self.assertIn("Output changed", names)
        self.assertIn("Rule deleted", names)
        self.assertIn("Unexpected output added", names)
        self.assertGreater(len(mutants), 5)

    def test_generated_lean_uses_state_outputs_model_and_properties(self):
        spec = load_initial_spec()
        lean = specchasm.render_lean_source(
            "test",
            spec,
            spec.model,
            spec.default,
        )

        self.assertIn("structure State", lean)
        self.assertIn("core_temperature : Nat", lean)
        self.assertIn("| Inject", lean)
        self.assertIn("def decideCommand", lean)
        self.assertIn("theorem P1", lean)
        self.assertNotIn("ReactorState", lean)

    def test_analyze_spec_uses_lean_result_as_mutant_oracle(self):
        spec = load_initial_spec()
        generated_count = len(specchasm.generate_mutants(spec))
        outcomes = [fake_check(True, "Original.lean")]
        outcomes.extend(
            fake_check(index % 2 == 0, f"M{index}.lean")
            for index in range(1, generated_count + 1)
        )

        with mock.patch("specchasm.find_lean_bin", return_value="/fake/lean"), mock.patch(
            "specchasm.run_lean_source", return_value=fake_check(False, "SpecChasmBatch.lean")
        ) as run_lean, mock.patch(
            "specchasm.check_from_batch", side_effect=outcomes
        ):
            analysis = specchasm.analyze_spec_data(spec, str(INITIAL_SPEC))

        self.assertEqual(1, run_lean.call_count)
        self.assertEqual(generated_count // 2, analysis.survived_count)
        self.assertTrue(analysis.original_check.ok)
        self.assertEqual("ECCS demo", analysis.spec_name)

    def test_malformed_spec_returns_clear_validation_error(self):
        with self.assertRaisesRegex(RuntimeError, "model rule is missing required key: then"):
            specchasm.Spec.from_data(
                {
                    "state": {"ready": "Bool"},
                    "outputs": ["Go", "Stop"],
                    "model": [{"when": ["ready = true"]}],
                    "default": "Stop",
                    "properties": [],
                },
                "bad_spec",
            )

    def test_analysis_reports_surviving_mutants(self):
        spec = load_initial_spec()
        outcomes = [fake_check(True, "Original.lean")]
        outcomes.extend(fake_check(True, f"M{i}.lean") for i in range(len(specchasm.generate_mutants(spec))))

        with mock.patch("specchasm.find_lean_bin", return_value="/fake/lean"), mock.patch(
            "specchasm.run_lean_source", return_value=fake_check(True, "SpecChasmBatch.lean")
        ), mock.patch(
            "specchasm.check_from_batch", side_effect=outcomes
        ):
            analysis = specchasm.analyze_spec_data(spec, str(INITIAL_SPEC))

        self.assertGreater(analysis.survived_count, 0)
        self.assertIn("def decideCommand", analysis.original_lean)
        self.assertTrue(all(mutant.status is specchasm.MutantStatus.SURVIVED for mutant in analysis.mutants))

    def test_json_output_has_stable_keys(self):
        spec = load_initial_spec()
        outcomes = [fake_check(True, "Original.lean")]
        outcomes.extend(fake_check(False, f"M{i}.lean") for i in range(len(specchasm.generate_mutants(spec))))

        with mock.patch("specchasm.find_lean_bin", return_value="/fake/lean"), mock.patch(
            "specchasm.run_lean_source", return_value=fake_check(False, "SpecChasmBatch.lean")
        ), mock.patch(
            "specchasm.check_from_batch", side_effect=outcomes
        ):
            analysis = specchasm.analyze_spec_data(spec, str(INITIAL_SPEC))

        payload = json.loads(json.dumps(analysis.to_json()))
        self.assertEqual(
            {
                "spec_source",
                "spec_name",
                "lean_bin",
                "original_check",
                "mutants",
                "summary",
            },
            set(payload.keys()),
        )
        self.assertEqual({"killed", "survived", "gaps"}, set(payload["summary"].keys()))


if __name__ == "__main__":
    unittest.main()
