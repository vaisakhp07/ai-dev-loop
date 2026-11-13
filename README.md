# AI Dev Loop — local Ollama + GitHub Actions + CodeRabbit

A **starter implementation**, not a proven production-grade autonomous developer. Uses a local Ollama coding model (no paid model API) and a Python controller on your Mac. This package includes the actual controller, unit tests, CodeRabbit config, CI workflow, and a sample task.



## Useful docs

- https://docs.ollama.com/api
- https://cli.github.com/manual/
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches
- https://www.coderabbit.ai/oss

The `--merge` mode also programmatically checks that `main` has branch protection requiring the `validate` check, and refuses if no protection exists. This is an extra guard, not a replacement for checking the repository settings.
