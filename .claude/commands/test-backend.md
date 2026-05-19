Run the backend test suite.

If $ARGUMENTS is provided, pass it directly to pytest (e.g., a test file path, module glob, or `-k expression`).

Steps:
1. Run: `cd backend && pytest $ARGUMENTS -v`
2. Report pass/fail counts
3. For any failures, show the test name and the key error line
4. If all pass, confirm what scope was tested

Common argument examples:
- `tests/test_auth.py` — auth only
- `tests/test_data_quality*.py` — all DQ tests
- `-k "similarity"` — tests matching "similarity"
- *(empty)* — full suite
