# Kiro Steering: Collaboration Contract

Kiro is the specification owner for this repository.

## Default Kiro Role

Use Kiro to produce:

- `requirements.md`
- `design.md`
- `tasks.md`
- acceptance criteria
- edge cases
- risk lists
- non-goals

Do not use Kiro for broad unsupervised implementation across core runtime
files. Implementation should be handed to Codex after the spec is accepted.

## Required Spec Shape

Every major spec under `.kiro/specs/<feature-id>/` should include:

1. Problem statement
2. User value
3. Functional requirements
4. Non-functional requirements
5. Data contracts and schema changes
6. Affected files and module boundaries
7. Failure and fallback behavior
8. Security and credential considerations
9. Acceptance criteria
10. Task list ordered by dependency

## Current Priority

The next planned spec is:

```text
.kiro/specs/video-provider-mainline/
```

Goal:

```text
Make real video generation the primary scene rendering path.
```

The spec must define:

- `shot_plan`
- video provider metadata
- provider failure fallback
- canonical timeline references
- review console visibility
- minimum sample workflow validation

## Handoff To Codex

When a spec is ready, summarize:

- files Codex should edit
- files Codex should not edit
- validation commands
- acceptance checklist
- known risks
