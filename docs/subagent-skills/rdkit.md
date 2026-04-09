# RDKit Skill

## Scope
- Use RDKit-backed tools for validation, descriptors, similarity, substructure, scaffold, and salt stripping.
- Prefer `tool_evaluate_molecule` over manually chaining validation and descriptor calls for new molecules.

## Execution Rules
- Treat `artifact_id` as the preferred input when available.
- Do not infer structure strings or descriptor values without a completed tool call.
- If a tool returns invalid chemistry, stop and report the validation failure instead of guessing a repair.

## Output Rules
- Keep final conclusions short and evidence-backed.
- Reference artifact ids instead of raw coordinate or structure payloads.