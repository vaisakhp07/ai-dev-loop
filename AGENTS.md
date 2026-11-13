# Repository development rules
- Build a Python 3.12 application using standard library where possible.
- Put application files in app/ and unit tests in tests/.
- Always supply automated tests for new behavior.
- Never introduce credentials, secrets, destructive commands, or remote installation scripts.
- Never modify .github/, .coderabbit.yaml, agent.py, AGENTS.md, or .gitignore.
- Keep code changes small and testable. Document how to run each application.
