Scaffold a new React component for the frontend.

$ARGUMENTS describes the component — e.g., "ExportButton that triggers a CSV download of DQ results".

Steps:
1. Read a similar existing component in `frontend/src/components/` for patterns
2. Create the component file — use `"use client"` only if it needs interactivity or browser APIs
3. Use CSS custom properties for colors (`--color-coral`, `--color-pickled-bluewood`, etc.), not hardcoded hex
4. Use Radix UI primitives for interactive elements (Dialog, Tooltip, DropdownMenu, etc.)
5. Use `cn()` for conditional class merging
6. Create a co-located `ComponentName.test.tsx` with at minimum a renders-without-crashing test
7. Import and use the component where needed

If the component fetches data:
- In a server component: use `fetch` with the `/api/*` path directly
- In a client component: use the helpers in `frontend/src/lib/` or standard `fetch`
