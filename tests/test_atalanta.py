import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
        self.assertEqual("Nat", spec.state["core_temperature"])
        self.assertEqual(["Inject", "Inhibit", "Fault"], spec.outputs)
        self.assertEqual(4, len(spec.model))
        self.assertEqual(4, len(spec.properties))

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
        self.assertTrue(analysis.original_check["ok"])
        self.assertEqual("ECCS demo", analysis.spec_name)

    def test_missing_input_file_returns_clear_cli_error(self):
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = atalanta.main(["does-not-exist.json"])

        self.assertEqual(2, exit_code)
        self.assertIn("spec file not found", stderr.getvalue())

    def test_strict_returns_nonzero_when_gaps_remain(self):
        spec = atalanta.load_spec(INITIAL_SPEC)
        outcomes = [fake_check(True, "Original.lean")]
        outcomes.extend(fake_check(True, f"M{i}.lean") for i in range(len(atalanta.generate_mutants(spec))))

        with mock.patch("atalanta.find_lean_bin", return_value="/fake/lean"), mock.patch(
            "atalanta.run_lean", side_effect=outcomes
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = atalanta.main(["examples/eccs_initial_spec.json", "--strict"])

        self.assertEqual(1, exit_code)
        self.assertIn("SURVIVED", stdout.getvalue())

    def test_json_output_has_stable_keys(self):
        spec = atalanta.load_spec(INITIAL_SPEC)
        outcomes = [fake_check(True, "Original.lean")]
        outcomes.extend(fake_check(False, f"M{i}.lean") for i in range(len(atalanta.generate_mutants(spec))))

        with mock.patch("atalanta.find_lean_bin", return_value="/fake/lean"), mock.patch(
            "atalanta.run_lean", side_effect=outcomes
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = atalanta.main(["examples/eccs_initial_spec.json", "--json"])

        payload = json.loads(stdout.getvalue())

        self.assertEqual(0, exit_code)
        self.assertEqual(
            {
                "spec_path",
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

    def test_non_file_path_returns_clear_cli_error(self):
        with tempfile.TemporaryDirectory() as directory:
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = atalanta.main([directory])

        self.assertEqual(2, exit_code)
        self.assertIn("spec path is not a file", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
