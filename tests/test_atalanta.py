import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import atalanta


ROOT = Path(__file__).resolve().parents[1]
INITIAL_SPEC = ROOT / "examples" / "eccs_initial_spec.json"
STRENGTHENED_SPEC = ROOT / "examples" / "eccs_strengthened_spec.json"


def fake_check(ok=True, path="generated.lean"):
    return atalanta.LeanCheck(
        ok=ok,
        path=path,
        stdout="",
        stderr="" if ok else "lean theorem failed",
        returncode=0 if ok else 1,
    )


class AtalantaLeanTests(unittest.TestCase):
    def test_loads_structured_spec(self):
        spec = atalanta.load_spec(INITIAL_SPEC)

        self.assertEqual("ECCS demo", spec.name)
        self.assertEqual(atalanta.StateType.NAT, spec.state["core_temperature"])
        self.assertEqual(["Inject", "Inhibit", "Fault"], spec.outputs)
        self.assertEqual(4, len(spec.model))
        self.assertEqual(4, len(spec.properties))

    def test_loads_structured_spec_from_text(self):
        raw_text = INITIAL_SPEC.read_text(encoding="utf-8")
        spec = atalanta.load_spec_text(raw_text, "browser_input")

        self.assertEqual("ECCS demo", spec.name)
        self.assertEqual(atalanta.StateType.NAT, spec.state["core_temperature"])
        self.assertEqual(["Inject", "Inhibit", "Fault"], spec.outputs)

    def test_generates_mutants_from_model_not_catalog(self):
        spec = atalanta.load_spec(INITIAL_SPEC)
        mutants = atalanta.generate_mutants(spec)

        names = {mutant.name for mutant in mutants}
        self.assertIn("Comparator changed", names)
        self.assertIn("Threshold changed", names)
        self.assertIn("Condition dropped", names)
        self.assertIn("Output changed", names)
        self.assertIn("Rule deleted", names)
        self.assertIn("Unexpected output added", names)
        self.assertGreater(len(mutants), 5)

    def test_generated_lean_uses_state_outputs_model_and_properties(self):
        spec = atalanta.load_spec(INITIAL_SPEC)
        lean = atalanta.render_lean_file(
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
        spec = atalanta.load_spec(INITIAL_SPEC)
        generated_count = len(atalanta.generate_mutants(spec))
        outcomes = [fake_check(True, "Original.lean")]
        outcomes.extend(
            fake_check(index % 2 == 0, f"M{index}.lean")
            for index in range(1, generated_count + 1)
        )

        with mock.patch("atalanta.find_lean_bin", return_value="/fake/lean"), mock.patch(
            "atalanta.run_lean", side_effect=outcomes
        ):
            analysis = atalanta.analyze_spec(INITIAL_SPEC)

        self.assertEqual(generated_count // 2, analysis.survived_count)
        self.assertTrue(analysis.original_check.ok)
        self.assertEqual("ECCS demo", analysis.spec_name)

    def test_malformed_spec_returns_clear_validation_error(self):
        with self.assertRaisesRegex(RuntimeError, "model rule is missing required key: then"):
            atalanta.load_spec_data(
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
        spec = atalanta.load_spec(INITIAL_SPEC)
        outcomes = [fake_check(True, "Original.lean")]
        outcomes.extend(fake_check(True, f"M{i}.lean") for i in range(len(atalanta.generate_mutants(spec))))

        with mock.patch("atalanta.find_lean_bin", return_value="/fake/lean"), mock.patch(
            "atalanta.run_lean", side_effect=outcomes
        ):
            analysis = atalanta.analyze_spec(INITIAL_SPEC)
            report = atalanta.render_text_report(analysis)

        self.assertGreater(analysis.survived_count, 0)
        self.assertIn("SURVIVED", report)

    def test_json_output_has_stable_keys(self):
        spec = atalanta.load_spec(INITIAL_SPEC)
        outcomes = [fake_check(True, "Original.lean")]
        outcomes.extend(fake_check(False, f"M{i}.lean") for i in range(len(atalanta.generate_mutants(spec))))

        with mock.patch("atalanta.find_lean_bin", return_value="/fake/lean"), mock.patch(
            "atalanta.run_lean", side_effect=outcomes
        ):
            analysis = atalanta.analyze_spec(INITIAL_SPEC)

        payload = json.loads(json.dumps(atalanta.analysis_to_json(analysis)))
        self.assertEqual(
            {
                "spec_source",
                "spec_name",
                "lean_bin",
                "work_dir",
                "original_check",
                "mutants",
                "summary",
            },
            set(payload.keys()),
        )
        self.assertEqual({"killed", "survived", "gaps"}, set(payload["summary"].keys()))

    def test_loading_directory_path_raises_os_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                atalanta.load_spec(Path(directory))


if __name__ == "__main__":
    unittest.main()
