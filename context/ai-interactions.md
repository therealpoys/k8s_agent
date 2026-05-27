# AI Interaction Guidelines

## Communication

- Be concise and direct
- Explain non-obvious decisions briefly
- Ask before large refactors or architectural changes
- Don't add features not in the project spec
- Never delete files without clarification
- Present a plan first and wait for explicit approval before writing any code

## Workflow

This is the common workflow that we will use for every single feature/fix:

1. **Document** - Document the feature in `context/current-feature.md`
2. **Branch** - Create new branch for feature, fix, etc
3. **Implement** - Implement the feature/fix described in `context/current-feature.md`
4. **Test** - `pytest -m "not integration"` ausführen, alle Tests müssen grün sein
5. **Iterate** - Iterate and change things if needed
6. **Commit** - Only after tests pass and everything works
7. **Merge** - Merge to main
8. **Delete Branch** - Delete branch after merge
9. **Review** - Review AI-generated code periodically and on demand
10. Mark as completed in `context/current-feature.md` and add to history

Do NOT commit without permission and until all tests pass. If tests fail, fix the issues first.

## Branching

We will create a new branch for every feature/fix. Name branch **feature/[feature]** or **fix/[fix]**, etc. Ask to delete the branch once merged.

## Commits

- Ask before committing (don't auto-commit)
- Use conventional commit messages (feat:, fix:, chore:, etc.)
- Keep commits focused (one feature/fix per commit)
- Never put "Generated With Claude" in the commit messages

## When Stuck

- If something isn't working after 2-3 attempts, stop and explain the issue
- Don't keep trying random fixes
- Ask for clarification if requirements are unclear

## Code Changes

- Make minimal changes to accomplish the task
- Don't refactor unrelated code unless asked
- Don't add "nice to have" features
- Preserve existing patterns in the codebase

## Testing

- Framework: **pytest** + `pytest-cov`
- Test-Ordner: `tests/unit/` und `tests/integration/`
- `conftest.py` mit gemeinsamen Fixtures:
  - `mock_http`: patcht `httpx` via `respx` oder `unittest.mock.patch` — keine echten HTTP-Requests in Unit Tests
  - `sample_feed`: liefert statische RSS-Feed-Strings für Fetcher-Tests
  - `sample_releases`: statische GitHub-API-Responses als Dict
- LiteLLM wird in Unit-Tests immer mit `unittest.mock.patch("litellm.completion")` gemockt
- Integration-Tests mit echten Feeds/API: `@pytest.mark.integration`, opt-in via `pytest -m integration`
- Default-Run (kein Netzwerk, kein LLM): `pytest -m "not integration"`
- Netzwerk-Operationen in Tests immer mocken — nie echte HTTP-Requests im Default-Run

## Code Review

Review AI-generated code periodically, especially for:

- Security (API-Key-Handling, kein Leaken von `.env`-Werten in Logs)
- Rate Limiting (GitHub API 60 req/h ohne Token)
- Error Handling (Feed-Timeouts, ungültige RSS-Formate, GitHub API 404s)
- LiteLLM Output Validation (Markdown-Format korrekt? Halluzinationen?)
