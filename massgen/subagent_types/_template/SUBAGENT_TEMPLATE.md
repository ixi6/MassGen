# SUBAGENT Template (Not Discovered)

This template is intentionally excluded from subagent discovery.

Create a new specialized subagent by copying this content to:

`massgen/subagent_types/<your_type>/SUBAGENT.md`

or project-level override path:

`.agent/subagent_types/<your_type>/SUBAGENT.md`

Use only the supported frontmatter keys.

```markdown
---
name: your_type_name
description: When to use: one-sentence usage guidance for this role
skills:
  - optional-skill-name
expected_input:
  - objective and scope
  - setup/prerequisites
  - commands or steps to execute
  - expected output format
---

You are a <type> subagent. Your role is to ...

## When to use
- ...

## Execution standards
- ...

## Deliverables / output format
- `Scope`:
- `Findings`:
- `Evidence`:
- `Open questions`:

## Do not
- ...
```

Rules:
- Keep description concise and explicit about when to use this role.
- Use evidence-first reporting; avoid unverifiable claims.
- The main agent remains responsible for final decisions.
