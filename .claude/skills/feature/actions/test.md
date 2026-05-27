# Test Action

1. Read current-feature.md to understand what was implemented
2. Identify modules and functions added/modified for this feature
3. Check if tests already exist for these functions in `tests/unit/` or `tests/integration/`
4. For functions without tests that have testable logic, write unit tests:
   - Place unit tests in `tests/unit/test_<module>.py`
   - Use `tmp_db` fixture (from conftest.py) for DB-dependent tests
   - Mock external dependencies (OllamaLLM, pdfplumber, pytesseract) with `unittest.mock.patch`
   - Test happy path and error/fallback cases
   - Do not write tests just to write them. Use your best judgement
5. Run `pytest -m "not integration"` to verify all tests pass
6. Report test coverage for the new feature code