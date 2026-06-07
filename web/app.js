const specEditor = document.querySelector("#specEditor");
const analyzeButton = document.querySelector("#analyzeButton");
const formatButton = document.querySelector("#formatButton");
const copyLean = document.querySelector("#copyLean");
const copyReport = document.querySelector("#copyReport");
const loadEccs = document.querySelector("#loadEccs");
const loadRail = document.querySelector("#loadRail");
const leanOutput = document.querySelector("#leanOutput");
const reportOutput = document.querySelector("#reportOutput");
const inputStatus = document.querySelector("#inputStatus");
const systemName = document.querySelector("#systemName");
const mutantCount = document.querySelector("#mutantCount");
const survivedCount = document.querySelector("#survivedCount");
const killedCount = document.querySelector("#killedCount");

const tooltipText = {
  mutants: "Generated alternative models created by changing conditions, thresholds, outputs, or rules.",
  survived: "A survived mutant still satisfies the written properties, which points to a possible spec gap.",
  killed: "A killed mutant violates at least one written property, so the current spec rules out that wrong behavior."
};

const sampleSpecs = {
  eccs: {
    "name": "ECCS demo",
    "state": {
      "coolant_pressure": "Nat",
      "core_temperature": "Nat",
      "injection_active": "Bool",
      "signal_valid": "Bool"
    },
    "outputs": ["Inject", "Inhibit", "Fault"],
    "model": [
      { "when": ["signal_valid = false"], "then": "Fault" },
      { "when": ["core_temperature > 650", "coolant_pressure < 1500"], "then": "Inject" },
      { "when": ["injection_active = true", "core_temperature >= 300"], "then": "Inject" },
      { "when": ["core_temperature > 650"], "then": "Fault" }
    ],
    "default": "Inhibit",
    "properties": [
      { "id": "P1", "when": ["signal_valid = true", "core_temperature > 650", "coolant_pressure < 1500"], "expect": "command = Inject" },
      { "id": "P2", "when": ["signal_valid = false"], "expect": "command = Fault" },
      { "id": "P3", "when": ["signal_valid = true", "injection_active = true", "core_temperature >= 300"], "expect": "command = Inject" },
      { "id": "P4", "when": ["core_temperature > 650"], "expect": "command != Inhibit" }
    ]
  },
  rail: {
    "name": "Rail crossing gate controller",
    "state": {
      "train_distance": "Nat",
      "train_speed": "Nat",
      "gate_lowered": "Bool",
      "sensor_valid": "Bool"
    },
    "outputs": ["Lower", "Raise", "Hold", "Fault"],
    "model": [
      { "when": ["sensor_valid = false"], "then": "Fault" },
      { "when": ["train_distance < 1000", "train_speed > 0"], "then": "Lower" },
      { "when": ["gate_lowered = true", "train_distance < 1500"], "then": "Hold" },
      { "when": ["train_distance > 2000"], "then": "Raise" }
    ],
    "default": "Hold",
    "properties": [
      { "id": "R1", "when": ["sensor_valid = false"], "expect": "command = Fault" },
      { "id": "R2", "when": ["sensor_valid = true", "train_distance < 1000", "train_speed > 0"], "expect": "command = Lower" },
      { "id": "R3", "when": ["gate_lowered = true", "train_distance < 1500"], "expect": "command != Raise" },
      { "id": "R4", "when": ["sensor_valid = true", "train_distance > 2000"], "expect": "command != Lower" }
    ]
  }
};

function parseCondition(raw) {
  const match = String(raw).match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(<=|>=|!=|=|<|>)\s*([A-Za-z0-9_]+)\s*$/);
  if (!match) throw new Error(`Invalid condition: ${raw}`);
  return { field: match[1], op: match[2], value: match[3], text: `${match[1]} ${match[2]} ${match[3]}` };
}

function parseExpectation(raw) {
  const match = String(raw).match(/^\s*command\s*(!=|=)\s*([A-Za-z_][A-Za-z0-9_]*)\s*$/);
  if (!match) throw new Error(`Invalid expectation: ${raw}`);
  return { op: match[1], output: match[2] };
}

function normalizeSpec(raw) {
  for (const key of ["state", "outputs", "model", "default", "properties"]) {
    if (!(key in raw)) throw new Error(`Spec is missing required key: ${key}`);
  }
  const outputs = raw.outputs.map(String);
  return {
    name: String(raw.name || "Untitled spec"),
    state: Object.fromEntries(Object.entries(raw.state).map(([key, value]) => [String(key), String(value)])),
    outputs,
    model: raw.model.map((rule) => ({
      when: (rule.when || []).map(parseCondition),
      output: String(rule.then)
    })),
    default: String(raw.default),
    properties: raw.properties.map((prop) => {
      const expect = parseExpectation(prop.expect);
      return {
        id: String(prop.id),
        when: (prop.when || []).map(parseCondition),
        expectOp: expect.op,
        expectOutput: expect.output
      };
    })
  };
}

function leanOutputName(output) {
  return `Command.${output}`;
}

function leanCondition(condition, hypothesis) {
  const left = `s.${condition.field}`;
  const right = /^(true|false)$/i.test(condition.value) ? condition.value.toLowerCase() : condition.value;
  let expr;
  if (condition.op === ">") expr = `${right} < ${left}`;
  else if (condition.op === ">=") expr = `${right} <= ${left}`;
  else if (condition.op === "=") expr = `${left} = ${right}`;
  else if (condition.op === "!=") expr = `${left} ≠ ${right}`;
  else expr = `${left} ${condition.op} ${right}`;
  return hypothesis ? `    (${hypothesis} : ${expr})` : expr;
}

function leanRuleCondition(rule) {
  return rule.when.length ? rule.when.map((cond) => leanCondition(cond)).join(" ∧ ") : "True";
}

function renderPrelude(spec, outputs = spec.outputs) {
  const constructors = outputs.map((output) => `  | ${output}`).join("\n");
  const fields = Object.entries(spec.state).map(([name, kind]) => `  ${name} : ${kind}`).join("\n");
  return `inductive Command where
${constructors}
deriving DecidableEq, Repr

structure State where
${fields}
deriving DecidableEq, Repr`;
}

function renderModel(rules, fallback) {
  const lines = ["def decideCommand (s : State) : Command :="];
  let indent = "  ";
  rules.forEach((rule, index) => {
    lines.push(`${indent}if hRule${index + 1} : ${leanRuleCondition(rule)} then`);
    lines.push(`${indent}  ${leanOutputName(rule.output)}`);
    lines.push(`${indent}else`);
    indent += "  ";
  });
  lines.push(`${indent}${leanOutputName(fallback)}`);
  return lines.join("\n");
}

function safeIdentifier(value) {
  const cleaned = String(value).replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  return cleaned && !/^\d/.test(cleaned) ? cleaned : `p_${cleaned}`;
}

function renderProperty(prop) {
  const hypotheses = prop.when.map((condition, index) => leanCondition(condition, `h${index + 1}`)).join("\n");
  const targetOp = prop.expectOp === "=" ? "=" : "≠";
  return `theorem ${safeIdentifier(prop.id)} (s : State)
${hypotheses}${hypotheses ? "\n" : ""}    :
    decideCommand s ${targetOp} ${leanOutputName(prop.expectOutput)} := by
  unfold decideCommand
  repeat' first | split | simp_all | omega`;
}

function renderLean(spec, rules = spec.model, fallback = spec.default, outputs = spec.outputs, title = "original model") {
  return `-- Generated by Atalanta. This file is intentionally small and self-contained.
set_option linter.unusedVariables false
set_option linter.unusedSimpArgs false

namespace AtalantaGenerated

${renderPrelude(spec, outputs)}

-- Candidate model: ${title}
${renderModel(rules, fallback)}

${spec.properties.map(renderProperty).join("\n\n")}

end AtalantaGenerated`;
}

function flipCondition(condition) {
  const flips = { "<": ">", ">": "<", "<=": ">=", ">=": "<=" };
  return flips[condition.op] ? { ...condition, op: flips[condition.op], text: `${condition.field} ${flips[condition.op]} ${condition.value}` } : null;
}

function shiftCondition(condition) {
  if (!["<", ">", "<=", ">="].includes(condition.op) || !/^\d+$/.test(condition.value)) return null;
  const value = Number(condition.value);
  const delta = Math.max(1, Math.floor(value / 4));
  const shifted = ["<", "<="].includes(condition.op) ? value + delta : Math.max(0, value - delta);
  return { ...condition, value: String(shifted), text: `${condition.field} ${condition.op} ${shifted}` };
}

function cloneRules(rules) {
  return rules.map((rule) => ({ when: rule.when.map((condition) => ({ ...condition })), output: rule.output }));
}

function propose(kind, rule, condition, oldOutput) {
  const conditions = rule.when.map((cond) => cond.text);
  const whenText = conditions.length ? conditions.join(" and ") : "the mutated rule is reachable";
  if (kind === "Condition dropped" && condition) {
    return `When ${condition.text} is false but the remaining rule conditions hold, command should not be ${rule.output}.`;
  }
  if (kind === "Comparator changed" && condition) {
    return `When ${whenText} and ${condition.text}, command should reject the comparator-mutated behavior.`;
  }
  if (kind === "Threshold changed" && condition) {
    return `Add an explicit boundary property around ${condition.text}.`;
  }
  if (kind === "Output changed" && oldOutput) {
    return `When ${whenText}, command should be ${rule.output}, not ${oldOutput}.`;
  }
  if (kind === "Rule deleted") {
    return `When ${whenText}, command should be ${rule.output}.`;
  }
  return "Add a property that distinguishes this mutated model from the intended model.";
}

function generateMutants(spec) {
  const mutants = [];
  const add = (name, summary, gap, proposedProperty, rules, fallback, outputs = spec.outputs) => {
    mutants.push({ id: `M${mutants.length + 1}`, name, summary, gap, proposedProperty, rules, default: fallback, outputs });
  };

  spec.model.forEach((rule, ruleIndex) => {
    rule.when.forEach((condition, conditionIndex) => {
      const flipped = flipCondition(condition);
      if (flipped) {
        const rules = cloneRules(spec.model);
        rules[ruleIndex].when[conditionIndex] = flipped;
        add("Comparator changed", `Changed ${condition.text} to ${flipped.text}.`, `The spec may not constrain the opposite side of ${condition.text}.`, propose("Comparator changed", rule, flipped), rules, spec.default);
      }

      const shifted = shiftCondition(condition);
      if (shifted && shifted.text !== condition.text) {
        const rules = cloneRules(spec.model);
        rules[ruleIndex].when[conditionIndex] = shifted;
        add("Threshold changed", `Changed ${condition.text} to ${shifted.text}.`, `The spec may not pin the boundary ${condition.text} tightly enough.`, propose("Threshold changed", rule, condition), rules, spec.default);
      }

      if (rule.when.length > 1) {
        const rules = cloneRules(spec.model);
        rules[ruleIndex].when.splice(conditionIndex, 1);
        add("Condition dropped", `Dropped ${condition.text} from a conjunctive rule.`, `The spec may not say ${condition.text} is necessary for ${rule.output}.`, propose("Condition dropped", rule, condition), rules, spec.default);
      }
    });

    spec.outputs.forEach((output) => {
      if (output === rule.output) return;
      const rules = cloneRules(spec.model);
      rules[ruleIndex].output = output;
      add("Output changed", `Changed rule output from ${rule.output} to ${output}.`, `The spec may not force ${rule.output} for this rule's state region.`, propose("Output changed", rule, null, output), rules, spec.default);
    });

    const deleted = cloneRules(spec.model);
    deleted.splice(ruleIndex, 1);
    add("Rule deleted", `Deleted the rule that returns ${rule.output}.`, "The spec may not require this rule's behavior.", propose("Rule deleted", rule), deleted, spec.default);
  });

  if (!spec.outputs.includes("Unexpected")) {
    add("Unexpected output added", "Added output Unexpected as the default result.", "The spec may not assert the output set is exhaustive.", `Command should be one of ${spec.outputs.join(", ")} under all states.`, cloneRules(spec.model), "Unexpected", [...spec.outputs, "Unexpected"]);
  }

  return mutants;
}

function valueFor(raw) {
  if (/^(true|false)$/i.test(raw)) return raw.toLowerCase() === "true";
  return Number(raw);
}

function evaluateCondition(condition, state) {
  const left = state[condition.field];
  const right = valueFor(condition.value);
  if (condition.op === "<") return left < right;
  if (condition.op === ">") return left > right;
  if (condition.op === "<=") return left <= right;
  if (condition.op === ">=") return left >= right;
  if (condition.op === "=") return left === right;
  if (condition.op === "!=") return left !== right;
  return false;
}

function decide(rules, fallback, state) {
  for (const rule of rules) {
    if (rule.when.every((condition) => evaluateCondition(condition, state))) return rule.output;
  }
  return fallback;
}

function propertyHolds(prop, command, state) {
  if (!prop.when.every((condition) => evaluateCondition(condition, state))) return true;
  return prop.expectOp === "=" ? command === prop.expectOutput : command !== prop.expectOutput;
}

function interestingValues(spec) {
  const values = {};
  Object.entries(spec.state).forEach(([field, kind]) => {
    if (kind === "Bool") {
      values[field] = [false, true];
      return;
    }
    const nums = new Set([0, 1, 2]);
    [...spec.model.flatMap((rule) => rule.when), ...spec.properties.flatMap((prop) => prop.when)].forEach((condition) => {
      if (condition.field !== field || !/^\d+$/.test(condition.value)) return;
      const n = Number(condition.value);
      [n - 1, n, n + 1, Math.max(0, Math.floor(n * 0.75)), Math.floor(n * 1.25)].forEach((candidate) => {
        if (candidate >= 0) nums.add(candidate);
      });
    });
    values[field] = [...nums].sort((a, b) => a - b).slice(0, 9);
  });
  return values;
}

function cartesianStates(valueMap) {
  const entries = Object.entries(valueMap);
  const states = [];
  const walk = (index, current) => {
    if (index === entries.length) {
      states.push({ ...current });
      return;
    }
    const [field, values] = entries[index];
    values.forEach((value) => {
      current[field] = value;
      walk(index + 1, current);
    });
  };
  walk(0, {});
  return states;
}

function analyzeSpec(spec) {
  const mutants = generateMutants(spec);
  const states = cartesianStates(interestingValues(spec));
  const originalFailures = states.flatMap((state) => {
    const command = decide(spec.model, spec.default, state);
    return spec.properties.filter((prop) => !propertyHolds(prop, command, state)).map((prop) => ({ prop, state, command }));
  });

  const results = mutants.map((mutant) => {
    const witness = states.find((state) => {
      const command = decide(mutant.rules, mutant.default, state);
      return spec.properties.some((prop) => !propertyHolds(prop, command, state));
    });
    const survived = !witness;
    return { ...mutant, status: survived ? "SURVIVED" : "KILLED", witness };
  });

  return { mutants, results, originalFailures, statesChecked: states.length };
}

function renderReport(spec, analysis) {
  const killed = analysis.results.filter((result) => result.status === "KILLED").length;
  const survived = analysis.results.length - killed;
  systemName.textContent = spec.name;
  mutantCount.textContent = String(analysis.results.length);
  survivedCount.textContent = String(survived);
  killedCount.textContent = String(killed);
  mutantCount.parentElement.title = tooltipText.mutants;
  survivedCount.parentElement.title = tooltipText.survived;
  killedCount.parentElement.title = tooltipText.killed;

  const original = analysis.originalFailures.length
    ? `<p class="muted">Original model failed ${analysis.originalFailures.length} bounded property checks.</p>`
    : `<p class="muted">Original model passed ${analysis.statesChecked} bounded property-state checks.</p>`;

  const rows = analysis.results.map((result) => {
    const survivedRow = result.status === "SURVIVED";
    const statusTip = survivedRow ? tooltipText.survived : tooltipText.killed;
    return `<div class="mutant-row ${survivedRow ? "survived" : "killed"}">
      <div class="mutant-title"><span>${result.id} ${escapeHtml(result.name)}</span><span class="badge" tabindex="0" data-tooltip="${escapeHtml(statusTip)}">${result.status}</span></div>
      <p>${escapeHtml(result.summary)}</p>
      ${survivedRow ? `<p>${escapeHtml(result.gap)}</p><p>${escapeHtml(result.proposedProperty)}</p>` : ""}
    </div>`;
  }).join("");

  reportOutput.innerHTML = `${original}<div class="report-list">${rows}</div>`;
}

function renderLeanReport(spec, payload) {
  const analysis = payload.analysis;
  const mutants = analysis.mutants || [];
  const killed = analysis.summary?.killed ?? mutants.filter((result) => result.status === "KILLED").length;
  const survived = analysis.summary?.survived ?? mutants.filter((result) => result.status === "SURVIVED").length;

  systemName.textContent = analysis.spec_name || spec.name;
  mutantCount.textContent = String(mutants.length);
  survivedCount.textContent = String(survived);
  killedCount.textContent = String(killed);
  mutantCount.parentElement.title = tooltipText.mutants;
  survivedCount.parentElement.title = tooltipText.survived;
  killedCount.parentElement.title = tooltipText.killed;

  const original = analysis.original_check?.ok
    ? `<p class="muted">Original model passed Lean verification.</p>`
    : `<p class="muted">Original model failed Lean verification.</p>`;

  const rows = mutants.map((result) => {
    const survivedRow = result.status === "SURVIVED";
    const statusTip = survivedRow ? tooltipText.survived : tooltipText.killed;
    return `<div class="mutant-row ${survivedRow ? "survived" : "killed"}">
      <div class="mutant-title"><span>${escapeHtml(result.id)} ${escapeHtml(result.name)}</span><span class="badge" tabindex="0" data-tooltip="${escapeHtml(statusTip)}">${escapeHtml(result.status)}</span></div>
      <p>${escapeHtml(result.summary)}</p>
      ${survivedRow ? `<p>${escapeHtml(result.gap)}</p><p>${escapeHtml(result.proposed_property)}</p>` : ""}
    </div>`;
  }).join("");

  reportOutput.innerHTML = `${original}<div class="report-list">${rows}</div>`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function loadSpecObject(spec) {
  specEditor.value = JSON.stringify(spec, null, 2);
  analyzeCurrentSpec();
}

function setAnalysisLoading(spec) {
  systemName.textContent = spec.name;
  mutantCount.textContent = "Analyzing";
  survivedCount.textContent = "-";
  killedCount.textContent = "-";
  inputStatus.innerHTML = `<span class="status-spinner" aria-hidden="true"></span> Running Lean-backed analysis...`;
  analyzeButton.disabled = true;
  analyzeButton.textContent = "Analyzing";
}

function clearAnalysisLoading() {
  analyzeButton.disabled = false;
  analyzeButton.textContent = "Analyze";
}

async function runLeanAnalysis(parsedSpec) {
  if (window.location.protocol === "file:") {
    throw new Error("Open this app through server.py to run Lean analysis.");
  }
  const response = await fetch("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(parsedSpec)
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Lean analysis failed");
  }
  return payload;
}

async function analyzeCurrentSpec() {
  try {
    const parsed = JSON.parse(specEditor.value);
    const spec = normalizeSpec(parsed);
    setAnalysisLoading(spec);
    try {
      const payload = await runLeanAnalysis(parsed);
      leanOutput.textContent = payload.lean;
      renderLeanReport(spec, payload);
      inputStatus.textContent = `Loaded ${spec.properties.length} properties and ${spec.model.length} model rules.`;
    } catch (serverError) {
      const lean = renderLean(spec);
      const analysis = analyzeSpec(spec);
      leanOutput.textContent = lean;
      renderReport(spec, analysis);
      inputStatus.textContent = `Loaded ${spec.properties.length} properties and ${spec.model.length} model rules. Static preview only: ${serverError.message}`;
    }
  } catch (error) {
    inputStatus.textContent = error.message;
    leanOutput.textContent = "";
    reportOutput.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
    systemName.textContent = "Invalid spec";
    mutantCount.textContent = "0";
    survivedCount.textContent = "0";
    killedCount.textContent = "0";
  } finally {
    clearAnalysisLoading();
  }
}

function copyText(text) {
  navigator.clipboard?.writeText(text);
}

formatButton.addEventListener("click", () => {
  const parsed = JSON.parse(specEditor.value);
  specEditor.value = JSON.stringify(parsed, null, 2);
});

analyzeButton.addEventListener("click", analyzeCurrentSpec);
copyLean.addEventListener("click", () => copyText(leanOutput.textContent));
copyReport.addEventListener("click", () => copyText(reportOutput.innerText));
loadEccs.addEventListener("click", () => loadSpecObject(sampleSpecs.eccs));
loadRail.addEventListener("click", () => loadSpecObject(sampleSpecs.rail));

loadSpecObject(sampleSpecs.eccs);
