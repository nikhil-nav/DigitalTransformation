List all specs and their current status.

$ARGUMENTS is optional — a status filter like `DRAFT`, `SCORED`, `APPROVED`, `IN_PROGRESS`, or `DONE`.

Steps:
1. `ls specs/*.md | sort` (excluding RULES.md and SPEC_TEMPLATE.md)
2. For each spec file, read the `**Status:**` line
3. If $ARGUMENTS is provided, filter to only specs matching that status
4. Output a table:

```
NNN  Status        Title
001  APPROVED      User authentication
002  IN_PROGRESS   BCM capability export
003  DRAFT         DQ email format check
```

5. Print a count summary at the bottom:
   `Total: N specs — X approved, Y in progress, Z draft`
