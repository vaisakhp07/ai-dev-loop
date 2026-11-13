# AI Dev Loop — local Ollama + GitHub Actions + CodeRabbit

A **starter implementation**, not a proven production-grade autonomous developer. Uses a local Ollama coding model (no paid model API) and a Python controller on your Mac. This package includes the actual controller, unit tests, CodeRabbit config, CI workflow, and a sample task.

## Critical limitations

- **Runs on your Mac, not in the cloud.** Keep the Mac powered, awake, online, and Ollama running. Do not expose Ollama's local API publicly.
- **The 7B model will make errors**, particularly with multi-file applications; the task size is deliberately small and changes limited to `app/` and `tests/`.
- **The local unit-test command executes AI-written code on your Mac.** `app/` and `tests/` restrictions are not a security sandbox. Use a disposable macOS user/container/VM with no credentials for serious work; do not ask it to run untrusted projects.
- **CodeRabbit can be rate-limited or unavailable.** An external review failure stops the controller rather than merging.
- **CodeRabbit's successful commit status means a review completed, NOT that the code is correct.** This controller additionally blocks on visible active, unresolved CodeRabbit review threads. There may be feedback that isn't represented as a thread. This is a limited, experimental gate, not a guarantee of correctness.
- **This controller does not automatically resolve comment threads** (because blindly resolving them would fabricate a successful review). A PR with unresolved threads may reach the retry limit and remain open for intervention.
- **This is free-tier-compatible, not guaranteed indefinitely free:** GitHub and CodeRabbit can apply limits and change terms.
- **Do not enable automatic deployment to production or give the agent production credentials.**

## 1. Prepare Mac

Already completed:

```bash
ollama pull qwen2.5-coder:7b
```

Install git and GitHub CLI (Homebrew):

```bash
brew install git gh
```

Verify:

```bash
ollama list
gh --version
gh auth login
```

Use GitHub.com, HTTPS, web-browser login, and authorize Git operations.

## 2. Create GitHub public repository

Extract this package to a directory (e.g. `~/ai-dev-loop`), then:

```bash
cd ~/ai-dev-loop
git init -b main
git add .
git commit -m "Initial AI dev loop scaffold"
gh repo create ai-dev-loop --public --source=. --remote=origin --push
```

If your GitHub account already has a repo with that name, choose another name.

Enable CodeRabbit's GitHub App for exactly this repo: https://app.coderabbit.ai/ (sign in with GitHub). Review its requested permissions carefully. For small new public repos, the agent triggers `@coderabbitai full review` automatically.

## 3. Protect main on GitHub (MANDATORY)

Repository → Settings → Branches → Add branch protection rule (or Rules → Rulesets):

- Branch pattern: `main`
- Require a pull request before merging
- Require status checks: select `validate` (the Actions job; a PR must run first before this check appears as an option)
- Require conversation resolution before merging (recommended)
- Block force pushes and deletion; do not enable bypasses
- **Do not require one human approval** if you intend completely unattended merging; CodeRabbit generally does not substitute for an approving human review.
- If possible, require that branches are up to date before merging.

If `validate` is not selectable yet, create a trivial PR and run CI, then return to configure protection **before enabling auto-merge**.

Repository → Settings → General → Pull Requests: enable squash merging. You need not enable GitHub native auto-merge because this controller merges only after its own checks.

**Verify branch protection yourself before using `--merge`.** The `doctor` command prints the branch-protection API response, but doesn't yet enforce its correctness programmatically.

## 4. Run the controller

For first test, use `doctor`, then a dry-run (creates/pushes a PR but does not merge):

```bash
python3 -m unittest discover -s tests -v
python3 agent.py doctor
python3 agent.py run examples/task.txt
```

If the dry-run PR passes both checks, it prints `READY TO MERGE` and leaves the PR open.

Once CI and CodeRabbit are working and branch protection is verified, use:

```bash
python3 agent.py run examples/task.txt --merge
```

Note: The script requires a clean working tree on `main` at the start; after the dry-run, it leaves you on the AI feature branch. To run a new task:

```bash
git switch main
git pull --ff-only
```

Write a different text file with app requirements, then:

```bash
python3 agent.py run my-task.txt --merge
```

## 5. How corrections happen

1. Prompt sent to local Ollama API `http://127.0.0.1:11434/api/chat`.
2. Model returns JSON listing files to write in `app/` and `tests/`.
3. Controller syntax-checks and runs unittests locally.
4. If local checks fail, retry model generation with error logs.
5. When local checks pass, commit to a `ai/task-*` branch and open PR.
6. Controller posts `@coderabbitai full review` and waits for latest-commit CI and CodeRabbit commit status.
7. Active unresolved CodeRabbit review threads are fed back to Ollama for a bounded repair cycle.
8. With CI successful and review status verified, `--merge` squash-merges the PR (provided GitHub branch protection allows it).

## 6. Known integration caveats

The CodeRabbit commit-status context/name and the GitHub App identity can vary by integration configuration. The controller **only accepts a commit status whose context and creator both contain `coderabbit`**, and otherwise waits, times out, and refuses to merge. If CodeRabbit only publishes a check run rather than that status in your account, the integration needs adaptation after inspecting a real PR.

`CodeRabbit review complete + no unresolved inline threads` is *not* an absolute endorsement. CodeRabbit may publish findings in top-level summaries or skip some files. Review this on your actual PR before trusting it.

CodeRabbit status may be delivered late; the polling timeout defaults to 900 seconds. Adjust `REVIEW_TIMEOUT` and `POLL_SECONDS` via environment variables.

CI only runs Python syntax and unittest discovery: this does not validate a full application, browser features, Docker, or cloud deployments. Add project-specific build and integration tests before expanding the agent.

## 7. Troubleshooting

```bash
ollama list
curl http://127.0.0.1:11434/api/tags
gh auth status
gh repo view
gh pr list
gh run list
```

Check the PR's Checks and Conversation tabs. A `CodeRabbit=pending` message means its recognizable commit status has not been found, not necessarily that no review is running. Never turn that into an implicit pass.

## Useful docs

- https://docs.ollama.com/api
- https://cli.github.com/manual/
- https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches
- https://www.coderabbit.ai/oss

The `--merge` mode also programmatically checks that `main` has branch protection requiring the `validate` check, and refuses if no protection exists. This is an extra guard, not a replacement for checking the repository settings.
