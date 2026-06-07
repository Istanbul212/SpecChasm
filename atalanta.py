#!/usr/bin/env python3
"""Atalanta: Lean-backed mutation-gap analyzer MVP."""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


class Operator(Enum):
    EQ = "="
    NE = "!="
    LT = "<"
    GT = ">"
    LE = "<="
    GE = ">="

    @classmethod
    def from_text(cls, value: str) -> "Operator":
        for operator in cls:
            if operator.value == value:
                return operator
        raise RuntimeError(f"invalid operator: {value!r}")


class StateType(Enum):
    NAT = "Nat"
    BOOL = "Bool"

    @classmethod
    def from_text(cls, value: str) -> "StateType":
        for state_type in cls:
            if state_type.value == value:
                return state_type
        raise RuntimeError(f"unsupported state field type: {value!r}")


class MutantStatus(Enum):
    KILLED = "KILLED"
    SURVIVED = "SURVIVED"


@dataclass(frozen=True)
class Condition:
    field: str
    op: Operator
    value: str

    @classmethod
    def from_text(cls, raw: str) -> "Condition":
        match = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|!=|=|<|>)\s*([A-Za-z0-9_]+)\s*", raw)
        if not match:
            raise RuntimeError(f"invalid condition: {raw!r}")
        return cls(match.group(1), Operator.from_text(match.group(2)), match.group(3))

    @property
    def text(self) -> str:
        return f"{self.field} {self.op.value} {self.value}"


@dataclass(frozen=True)
class Rule:
    when: Tuple[Condition, ...]
    output: str


@dataclass(frozen=True)
class Expectation:
    op: Operator
    output: str

    @classmethod
    def from_text(cls, raw: str) -> "Expectation":
        match = re.fullmatch(r"\s*command\s*(!=|=)\s*([A-Za-z_][A-Za-z0-9_]*)\s*", raw)
        if not match:
            raise RuntimeError(f"invalid property expectation: {raw!r}")
        return cls(Operator.from_text(match.group(1)), match.group(2))


@dataclass(frozen=True)
class Property:
    property_id: str
    when: Tuple[Condition, ...]
    expectation: Expectation


@dataclass(frozen=True)
class Spec:
    name: str
    state: Dict[str, StateType]
    outputs: List[str]
    model: List[Rule]
    default: str
    properties: List[Property]

    @classmethod
    def from_data(cls, raw: Dict[str, Any], spec_name: str) -> "Spec":
        required = ("state", "outputs", "model", "default", "properties")
        missing = [key for key in required if key not in raw]
        if missing:
            raise RuntimeError(f"spec is missing required keys: {', '.join(missing)}")

        state_value = raw["state"]
        outputs_value = raw["outputs"]
        model_value = raw["model"]
        default_value = raw["default"]
        properties_value = raw["properties"]

        if not isinstance(state_value, dict):
            raise RuntimeError("spec state must be a JSON object")
        if not isinstance(outputs_value, list):
            raise RuntimeError("spec outputs must be a JSON array")
        if not isinstance(model_value, list):
            raise RuntimeError("spec model must be a JSON array")
        if not isinstance(properties_value, list):
            raise RuntimeError("spec properties must be a JSON array")

        if not all(isinstance(name, str) for name in state_value):
            raise RuntimeError("spec state field names must be strings")
        if not all(isinstance(kind, str) for kind in state_value.values()):
            raise RuntimeError("spec state field types must be strings")
        state = {name: StateType.from_text(kind) for name, kind in state_value.items()}
        if not all(isinstance(output, str) for output in outputs_value):
            raise RuntimeError("spec outputs must contain only strings")
        if not isinstance(default_value, str):
            raise RuntimeError("spec default must be a string")

        outputs = outputs_value
        default = default_value
        if default not in outputs:
            raise RuntimeError(f"default output {default!r} is not listed in outputs")

        model = []
        for item in model_value:
            if not isinstance(item, dict):
                raise RuntimeError("each model rule must be a JSON object")
            output = required_string(item, "then", "model rule")
            if output not in outputs:
                raise RuntimeError(f"model output {output!r} is not listed in outputs")
            model.append(
                Rule(
                    when=condition_list(item, "model rule"),
                    output=output,
                )
            )

        properties = []
        for item in properties_value:
            if not isinstance(item, dict):
                raise RuntimeError("each property must be a JSON object")
            expectation = Expectation.from_text(required_string(item, "expect", "property"))
            if expectation.output not in outputs:
                raise RuntimeError(f"property output {expectation.output!r} is not listed in outputs")
            properties.append(
                Property(
                    property_id=required_string(item, "id", "property"),
                    when=condition_list(item, "property"),
                    expectation=expectation,
                )
            )

        return cls(
            name=raw["name"] if isinstance(raw.get("name"), str) else spec_name,
            state=state,
            outputs=outputs,
            model=model,
            default=default,
            properties=properties,
        )


@dataclass(frozen=True)
class Mutant:
    mutant_id: str
    name: str
    summary: str
    gap: str
    proposed_property: str
    model: List[Rule]
    default: str
    outputs: List[str]


@dataclass(frozen=True)
class LeanCheck:
    ok: bool
    path: str
    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True)
class MutantResult:
    mutant_id: str
    name: str
    status: MutantStatus
    summary: str
    gap: str
    proposed_property: str
    lean_check: LeanCheck


@dataclass(frozen=True)
class Analysis:
    spec_source: str
    spec_name: str
    lean_bin: str
    original_lean: str
    original_check: LeanCheck
    mutants: List[MutantResult]

    @property
    def killed_count(self) -> int:
        return sum(1 for mutant in self.mutants if mutant.status is MutantStatus.KILLED)

    @property
    def survived_count(self) -> int:
        return sum(1 for mutant in self.mutants if mutant.status is MutantStatus.SURVIVED)


def required_value(item: Dict[str, Any], key: str, context: str) -> Any:
    if key not in item:
        raise RuntimeError(f"{context} is missing required key: {key}")
    return item[key]


def required_string(item: Dict[str, Any], key: str, context: str) -> str:
    value = required_value(item, key, context)
    if not isinstance(value, str):
        raise RuntimeError(f"{context} key {key!r} must be a string")
    return value


def condition_list(item: Dict[str, Any], context: str) -> Tuple[Condition, ...]:
    raw_conditions = item.get("when", [])
    if not isinstance(raw_conditions, list):
        raise RuntimeError(f"{context} key 'when' must be a JSON array")
    if not all(isinstance(cond, str) for cond in raw_conditions):
        raise RuntimeError(f"{context} key 'when' must contain only strings")
    return tuple(Condition.from_text(cond) for cond in raw_conditions)


def lean_output(output: str) -> str:
    return f"Command.{output}"


def lean_condition(condition: Condition, hypothesis: Optional[str] = None) -> str:
    left = f"s.{condition.field}"
    right = condition.value.lower() if condition.value.lower() in ("true", "false") else condition.value

    lean_ops = {
        Operator.GT: f"{right} < {left}",
        Operator.GE: f"{right} <= {left}",
        Operator.EQ: f"{left} = {right}",
        Operator.NE: f"{left} ≠ {right}",
        Operator.LT: f"{left} < {right}",
        Operator.LE: f"{left} <= {right}",
    }
    expr = lean_ops[condition.op]

    if hypothesis:
        return f"({hypothesis} : {expr})"
    return expr


def lean_rule_condition(rule: Rule) -> str:
    if not rule.when:
        return "True"
    return " ∧ ".join(lean_condition(cond) for cond in rule.when)


def render_prelude(spec: Spec, outputs: Optional[List[str]] = None) -> str:
    output_names = outputs if outputs is not None else spec.outputs
    constructors = "\n".join(f"  | {output}" for output in output_names)
    fields = "\n".join(f"  {name} : {kind.value}" for name, kind in spec.state.items())
    return f"""\
inductive Command where
{constructors}
deriving DecidableEq, Repr

structure State where
{fields}
deriving DecidableEq, Repr
"""


def render_model(rules: Sequence[Rule], default: str) -> str:
    lines = ["def decideCommand (s : State) : Command :="]
    indent = "  "
    for index, rule in enumerate(rules, start=1):
        lines.append(f"{indent}if hRule{index} : {lean_rule_condition(rule)} then")
        lines.append(f"{indent}  {lean_output(rule.output)}")
        lines.append(f"{indent}else")
        indent += "  "
    lines.append(f"{indent}{lean_output(default)}")
    return "\n".join(lines)


def render_property(prop: Property) -> str:
    hypotheses = []
    for index, condition in enumerate(prop.when, start=1):
        hypotheses.append(f"    {lean_condition(condition, f'h{index}')}")
    hypothesis_block = "\n".join(hypotheses)
    separator = "\n" if hypothesis_block else ""
    target_op = "=" if prop.expectation.op is Operator.EQ else "≠"
    theorem_name = safe_identifier(prop.property_id)
    return f"""\
theorem {theorem_name} (s : State)
{hypothesis_block}{separator}    :
    decideCommand s {target_op} {lean_output(prop.expectation.output)} := by
  unfold decideCommand
  repeat' first | split | simp_all | omega
"""


def render_lean_source(
    title: str,
    spec: Spec,
    rules: Sequence[Rule],
    default: str,
    outputs: Optional[List[str]] = None,
) -> str:
    theorem_code = "\n\n".join(render_property(prop) for prop in spec.properties)
    return f"""\
-- Generated by Atalanta.
namespace AtalantaGenerated

{render_prelude(spec, outputs)}

-- Candidate model: {title}
{render_model(rules, default)}

{theorem_code}

end AtalantaGenerated
"""


def flip_condition(condition: Condition) -> Optional[Condition]:
    flips = {
        Operator.LT: Operator.GT,
        Operator.GT: Operator.LT,
        Operator.LE: Operator.GE,
        Operator.GE: Operator.LE,
    }
    if condition.op not in flips:
        return None
    return replace(condition, op=flips[condition.op])


def shift_condition(condition: Condition) -> Optional[Condition]:
    if condition.op not in (Operator.LT, Operator.GT, Operator.LE, Operator.GE) or not condition.value.isdigit():
        return None
    value = int(condition.value)
    delta = max(1, value // 4)
    shifted = value + delta if condition.op in (Operator.LT, Operator.LE) else max(0, value - delta)
    return replace(condition, value=str(shifted))


def propose_property_from_mutant(mutant_kind: str, rule: Rule, condition: Optional[Condition], old_output: Optional[str]) -> str:
    conditions = [cond.text for cond in rule.when]
    if condition is not None and condition.text not in conditions:
        conditions.append(condition.text)
    when_text = " and ".join(conditions) if conditions else "the mutated rule is reachable"

    if mutant_kind == "condition dropped" and condition is not None:
        return f"When {condition.text} is false but the remaining rule conditions hold, command should not be {rule.output}."
    if mutant_kind == "comparator changed" and condition is not None:
        return f"When {when_text}, command should not accept the comparator-mutated behavior."
    if mutant_kind == "threshold changed" and condition is not None:
        return f"Add an explicit boundary property around {condition.field} {condition.op.value} {condition.value}."
    if mutant_kind == "output changed" and old_output is not None:
        return f"When {when_text}, command should be {rule.output}, not {old_output}."
    if mutant_kind == "rule deleted":
        return f"When {when_text}, command should be {rule.output}."
    return "Add a property that distinguishes this mutated model from the intended model."


MutantAdder = Callable[[str, str, str, str, List[Rule], str, Optional[List[str]]], None]


def replace_condition_in_model(spec: Spec, rule_index: int, condition_index: int, condition: Condition) -> List[Rule]:
    rules = list(spec.model)
    rule = rules[rule_index]
    new_when = list(rule.when)
    new_when[condition_index] = condition
    rules[rule_index] = replace(rule, when=tuple(new_when))
    return rules


def remove_condition_from_model(spec: Spec, rule_index: int, condition_index: int) -> List[Rule]:
    rules = list(spec.model)
    rule = rules[rule_index]
    new_when = [cond for idx, cond in enumerate(rule.when) if idx != condition_index]
    rules[rule_index] = replace(rule, when=tuple(new_when))
    return rules


def replace_rule_output(spec: Spec, rule_index: int, output: str) -> List[Rule]:
    rules = list(spec.model)
    rules[rule_index] = replace(rules[rule_index], output=output)
    return rules


def delete_rule(spec: Spec, rule_index: int) -> List[Rule]:
    return [existing for idx, existing in enumerate(spec.model) if idx != rule_index]


def add_condition_mutants(add: MutantAdder, spec: Spec, rule_index: int, rule: Rule) -> None:
    for cond_index, condition in enumerate(rule.when):
        flipped = flip_condition(condition)
        if flipped is not None:
            add(
                "Comparator changed",
                f"Changed `{condition.text}` to `{flipped.text}` in a model rule.",
                f"The spec may not constrain the opposite side of `{condition.text}`.",
                propose_property_from_mutant("comparator changed", rule, flipped, None),
                replace_condition_in_model(spec, rule_index, cond_index, flipped),
                spec.default,
                None,
            )

        shifted = shift_condition(condition)
        if shifted is not None and shifted != condition:
            add(
                "Threshold changed",
                f"Changed `{condition.text}` to `{shifted.text}` in a model rule.",
                f"The spec may not pin the boundary `{condition.text}` tightly enough.",
                propose_property_from_mutant("threshold changed", rule, condition, None),
                replace_condition_in_model(spec, rule_index, cond_index, shifted),
                spec.default,
                None,
            )

        if len(rule.when) > 1:
            add(
                "Condition dropped",
                f"Dropped `{condition.text}` from a conjunctive model rule.",
                f"The spec may not say `{condition.text}` is necessary for `{rule.output}`.",
                propose_property_from_mutant("condition dropped", rule, condition, None),
                remove_condition_from_model(spec, rule_index, cond_index),
                spec.default,
                None,
            )


def add_output_mutants(add: MutantAdder, spec: Spec, rule_index: int, rule: Rule) -> None:
    for output in spec.outputs:
        if output == rule.output:
            continue
        add(
            "Output changed",
            f"Changed rule output from `{rule.output}` to `{output}`.",
            f"The spec may not force `{rule.output}` for this rule's state region.",
            propose_property_from_mutant("output changed", rule, None, output),
            replace_rule_output(spec, rule_index, output),
            spec.default,
            None,
        )


def add_rule_deletion_mutant(add: MutantAdder, spec: Spec, rule_index: int, rule: Rule) -> None:
    add(
        "Rule deleted",
        f"Deleted the rule that returns `{rule.output}`.",
        f"The spec may not require this rule's behavior.",
        propose_property_from_mutant("rule deleted", rule, None, None),
        delete_rule(spec, rule_index),
        spec.default,
        None,
    )


def add_totality_mutant(add: MutantAdder, spec: Spec) -> None:
    extra_output = "Unexpected"
    if extra_output in spec.outputs:
        return
    add(
        "Unexpected output added",
        f"Added output `{extra_output}` as the default result.",
        "The spec may not assert the output set is exhaustive.",
        f"Command should be one of {', '.join(spec.outputs)} under all states.",
        list(spec.model),
        extra_output,
        spec.outputs + [extra_output],
    )


def generate_mutants(spec: Spec) -> List[Mutant]:
    mutants: List[Mutant] = []

    def add(name: str, summary: str, gap: str, proposed: str, rules: List[Rule], default: str, outputs: Optional[List[str]] = None) -> None:
        mutants.append(
            Mutant(
                mutant_id=f"M{len(mutants) + 1}",
                name=name,
                summary=summary,
                gap=gap,
                proposed_property=proposed,
                model=rules,
                default=default,
                outputs=outputs if outputs is not None else spec.outputs,
            )
        )

    for rule_index, rule in enumerate(spec.model):
        add_condition_mutants(add, spec, rule_index, rule)
        add_output_mutants(add, spec, rule_index, rule)
        add_rule_deletion_mutant(add, spec, rule_index, rule)

    add_totality_mutant(add, spec)

    return mutants


def find_lean_bin(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit
    path_bin = shutil.which("lean")
    if path_bin:
        return path_bin
    home_bin = Path.home() / ".elan" / "bin" / "lean"
    if home_bin.exists():
        return str(home_bin)
    return None


def run_lean_source(lean_bin: str, source_name: str, lean_source: str) -> LeanCheck:
    env = os.environ.copy()
    env.setdefault("ELAN_NO_UPDATE_CHECK", "1")
    env.setdefault("LEAN_ABORT_ON_PANIC", "1")
    completed = subprocess.run(
        [lean_bin, "--stdin"],
        env=env,
        input=lean_source,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return LeanCheck(
        ok=completed.returncode == 0,
        path=source_name,
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
    )


def render_and_check(
    lean_bin: str,
    source_name: str,
    title: str,
    spec: Spec,
    rules: Sequence[Rule],
    default: str,
    outputs: Optional[List[str]] = None,
) -> Tuple[str, LeanCheck]:
    lean_source = render_lean_source(title, spec, rules, default, outputs)
    return lean_source, run_lean_source(lean_bin, source_name, lean_source)


def check_to_json(check: LeanCheck) -> Dict[str, object]:
    return {
        "ok": check.ok,
        "path": check.path,
        "stdout": check.stdout,
        "stderr": check.stderr,
        "returncode": check.returncode,
    }


def analyze_spec_data(
    spec: Spec,
    spec_source: str,
    lean_bin: Optional[str] = None,
) -> Analysis:
    resolved_lean_bin = find_lean_bin(lean_bin)
    if not resolved_lean_bin:
        raise RuntimeError("Lean executable not found. Install elan or pass --lean-bin.")

    original_lean, original_check = render_and_check(
        resolved_lean_bin,
        "Original.lean",
        "original model",
        spec,
        spec.model,
        spec.default,
    )

    mutant_results = []
    for mutant in generate_mutants(spec):
        _, check = render_and_check(
            resolved_lean_bin,
            f"{mutant.mutant_id}_{safe_identifier(mutant.name)}.lean",
            mutant.name,
            spec,
            mutant.model,
            mutant.default,
            mutant.outputs,
        )
        survived = check.ok
        mutant_results.append(
            MutantResult(
                mutant_id=mutant.mutant_id,
                name=mutant.name,
                status=MutantStatus.SURVIVED if survived else MutantStatus.KILLED,
                summary=mutant.summary,
                gap=mutant.gap if survived else "",
                proposed_property=mutant.proposed_property if survived else "",
                lean_check=check,
            )
        )

    return Analysis(
        spec_source=spec_source,
        spec_name=spec.name,
        lean_bin=resolved_lean_bin,
        original_lean=original_lean,
        original_check=original_check,
        mutants=mutant_results,
    )


def safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"p_{cleaned}"
    return cleaned


def analysis_to_json(analysis: Analysis) -> Dict[str, object]:
    return {
        "spec_source": analysis.spec_source,
        "spec_name": analysis.spec_name,
        "lean_bin": analysis.lean_bin,
        "original_check": check_to_json(analysis.original_check),
        "mutants": [
            {
                "id": mutant.mutant_id,
                "name": mutant.name,
                "status": mutant.status.value,
                "summary": mutant.summary,
                "gap": mutant.gap,
                "proposed_property": mutant.proposed_property,
                "lean_check": check_to_json(mutant.lean_check),
            }
            for mutant in analysis.mutants
        ],
        "summary": {
            "killed": analysis.killed_count,
            "survived": analysis.survived_count,
            "gaps": analysis.survived_count,
        },
    }
