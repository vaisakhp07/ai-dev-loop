#!/usr/bin/env python3
"""Local Ollama -> GitHub PR -> CI + CodeRabbit -> bounded repair -> merge.

Only run against a disposable/public sandbox repository initially. The agent runs
untrusted generated Python tests locally; use a VM/container for real isolation.
"""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
MODEL = os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:7b')
MAX_ATTEMPTS = int(os.getenv('MAX_ATTEMPTS', '4'))
POLL_SECONDS = int(os.getenv('POLL_SECONDS', '25'))
REVIEW_TIMEOUT = int(os.getenv('REVIEW_TIMEOUT', '900'))
MAX_FILES = 12
MAX_FILE_BYTES = 50000
MAX_PROMPT_FILE_BYTES = 5000


def sh(*args, check=True, timeout=180):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(args)}\n{p.stdout[-2500:]}\n{p.stderr[-2500:]}")
    return p.stdout.strip()


def gh_json(*args):
    return json.loads(sh('gh', *args))


def extract_json_object(s):
    s = s.strip()
    if s.startswith('```'):
        s = '\n'.join(s.splitlines()[1:])
        if s.rstrip().endswith('```'):
            s = s.rstrip()[:-3]
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for m in re.finditer(r'\{', s):
            try:
                result, _ = decoder.raw_decode(s[m.start():])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                continue
        raise ValueError('Model did not produce a valid JSON object')


def allowed_path(name):
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        return False
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in ('.', '..') for part in name.split('/')):
        return False
    if p.parts[0] not in ('app', 'tests') or len(p.parts) < 2:
        return False
    if any(part.startswith('.') or part == '__pycache__' for part in p.parts):
        return False
    return p.suffix in ('.py', '.md', '.json', '.txt', '.toml')


def validate_ops(data, root=ROOT):
    files = data.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError(f'Expected 1..{MAX_FILES} files in JSON files array')
    seen = set()
    out = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError('Invalid file entry')
        name, content = item.get('path'), item.get('content')
        if not allowed_path(name) or not isinstance(content, str):
            raise ValueError(f'Forbidden path or nonstring content: {name!r}')
        if len(content.encode()) > MAX_FILE_BYTES or name in seen:
            raise ValueError(f'Duplicate/oversized content: {name}')
        dest = root / name
        if dest.is_symlink() or any(x.is_symlink() for x in dest.parents if x != root and root in x.parents):
            raise ValueError(f'Symlink path rejected: {name}')
        if not dest.resolve().is_relative_to(root.resolve()):
            raise ValueError(f'Escaping repo: {name}')
        seen.add(name)
        out.append((name, content))
    return out


def existing_files():
    data = {}
    for folder in ('app', 'tests'):
        for p in sorted((ROOT / folder).rglob('*')) if (ROOT / folder).exists() else []:
            if p.is_file() and not p.is_symlink() and allowed_path(str(p.relative_to(ROOT))):
                if p.stat().st_size <= MAX_PROMPT_FILE_BYTES and len(data) < 35:
                    data[str(p.relative_to(ROOT))] = p.read_text(errors='replace')
    return data


def ollama(prompt):
    body = json.dumps({
        'model': MODEL,
        'stream': False,
        'format': 'json',
        'options': {'temperature': 0.1, 'num_ctx': 8192},
        'messages': [
            {'role': 'system', 'content': (
                'You are a careful Python 3.12 developer. Respond with ONLY one JSON object of '
                'shape {"files":[{"path":"app/x.py","content":"full replacement content"},...]}. '
                'Write full files, never diffs or shell commands. Only paths under app/ or tests/. '
                'Build working functionality and unittest tests. Do not modify existing entrypoints '
                'outside those folders. Keep each response small, at most 12 files. '
                'Never include secrets or destructive operations.')},
            {'role': 'user', 'content': prompt},
        ],
    }).encode()
    req = urllib.request.Request('http://127.0.0.1:11434/api/chat', data=body,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=900) as resp:
        out = json.loads(resp.read())
    return extract_json_object(out['message']['content'])


def generate(task, feedback):
    prompt = json.dumps({'task': task, 'existing_files': existing_files(),
                         'feedback_to_fix': feedback[-12000:],
                         'repair_guidance': ('When feedback identifies a SyntaxError, fix that exact line first. '
                          'If an error says unterminated string literal, check mismatched quote characters '
                          'and replace accidental literal newlines inside strings with a backslash-n escape. '
                          'Return the COMPLETE corrected file, not a diff. Do not repeat the same invalid code. '
                          'Keep solutions minimal; avoid command-line UI unless the task demands it.')}, ensure_ascii=False)
    ops = validate_ops(ollama(prompt))
    # Reject invalid generated Python before overwriting existing files.
    for name, content in ops:
        if name.endswith('.py'):
            try:
                compile(content, name, 'exec')
            except SyntaxError as exc:
                raise ValueError(f'Generated invalid Python in {name}:{exc.lineno}: {exc.msg}; line={exc.text!r}') from exc
    for name, content in ops:
        p = ROOT / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    print('Wrote:', ', '.join(name for name, _ in ops), flush=True)


def local_tests():
    try:
        a = sh(sys.executable, '-m', 'compileall', '-q', 'app', 'tests', timeout=60)
        b = sh(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v', timeout=120)
        return True, a + '\n' + b
    except Exception as ex:
        return False, str(ex)[-6000:]


def repo_info():
    return gh_json('repo', 'view', '--json', 'nameWithOwner,isPrivate,defaultBranchRef')


def git_head():
    return sh('git', 'rev-parse', 'HEAD')


def commit_push(branch, number):
    # Stage only the content folders; never let LLM touch Actions or the controller.
    sh('git', 'add', '--', 'app', 'tests')
    if not sh('git', 'diff', '--cached', '--name-only'):
        raise RuntimeError('Model generated no changed files')
    sh('git', 'commit', '-m', f'ai: implement task (revision {number})')
    sh('git', 'push', '-u', 'origin', branch, timeout=120)


def pr_threads(owner, repo, number):
    query = '''query($owner:String!, $repo:String!, $number:Int!) {
      repository(owner:$owner,name:$repo) { pullRequest(number:$number) {
        reviewThreads(first:100) { pageInfo {hasNextPage} nodes {
          isResolved isOutdated comments(first:30) { nodes {
            body author {login} createdAt
          } }
        } }
      } } }'''
    data = gh_json('api', 'graphql', '-f', f'query={query}', '-f', f'owner={owner}',
                   '-f', f'repo={repo}', '-F', f'number={number}')
    result = data['data']['repository']['pullRequest']['reviewThreads']
    if result['pageInfo']['hasNextPage']:
        raise RuntimeError('Too many review threads: manual investigation required')
    return result['nodes']



def review_snapshot(owner, repo, number, sha):
    data = gh_json(
        'api',
        f'repos/{owner}/{repo}/commits/{sha}/check-runs',
        '--method', 'GET',
        '-f', 'per_page=100'
    )

    runs = data.get('check_runs', [])
    matches = [
        r for r in runs
        if r.get('name') == 'CodeRabbit'
        and (r.get('app') or {}).get('slug') == 'coderabbitai'
        and r.get('head_sha') == sha
    ]

    if not matches:
        return 'pending', 'No CodeRabbit check for current HEAD'

    latest = max(
        matches,
        key=lambda r: (r.get('started_at') or '', r.get('id', 0))
    )

    if latest.get('status') != 'completed':
        return 'pending', 'CodeRabbit review running'

    conclusion = latest.get('conclusion')
    if conclusion != 'success':
        if conclusion in ('failure', 'timed_out', 'cancelled'):
            return 'blocked', f'CodeRabbit: {conclusion}'
        return 'pending', f'CodeRabbit: {conclusion}'

    threads = pr_threads(owner, repo, number)
    unresolved = []

    for thread in threads:
        if thread['isResolved']:
            continue

        comments = thread['comments']['nodes']
        bot_comments = [
            c for c in comments
            if 'coderabbit' in
            (c.get('author') or {}).get('login', '').lower()
        ]

        if not bot_comments:
            continue

        original = bot_comments[0]
        recent = comments[-3:]
        selected = [original] + [
            c for c in recent if c is not original
        ]

        feedback = '\n'.join(
            c['body'][:1400] for c in selected
        )
        unresolved.append(feedback)

    if unresolved:
        return 'issues', '\n\n'.join(unresolved)[:10000]

    return 'clear', (
        'CodeRabbit check passed for current HEAD; '
        'no unresolved CodeRabbit threads'
    )


def ci_state(number):
    # Inspect required CI job directly, not the overall mixed list of bot checks.
    pr = gh_json('pr', 'view', str(number), '--json', 'headRefOid')
    sha = pr['headRefOid']
    checks = gh_json('api', f'repos/{repo_info()["nameWithOwner"]}/commits/{sha}/check-runs')['check_runs']
    ours = [c for c in checks if c['name'] == 'validate' and c.get('app', {}).get('slug') == 'github-actions']
    if not ours:
        return 'pending', 'CI job validate has not appeared'
    latest = sorted(ours, key=lambda c: c['started_at'] or '')[-1]
    if latest['status'] != 'completed':
        return 'pending', f'CI status: {latest["status"]}'
    if latest['conclusion'] == 'success':
        return 'clear', 'CI validate success'
    return 'issues', f'CI validate failed: {latest.get("html_url", "")}; conclusion={latest["conclusion"]}'


def review_and_ci(owner, repo, number, sha):
    deadline = time.monotonic() + REVIEW_TIMEOUT
    while time.monotonic() < deadline:
        # Never trust checks from a superseded commit.
        current = gh_json('pr', 'view', str(number), '--json', 'headRefOid')['headRefOid']
        if current != sha:
            raise RuntimeError('PR HEAD was changed externally; refusing to merge')
        ci, details = ci_state(number)
        rev, feedback = review_snapshot(owner, repo, number, sha)
        print(f'  CI={ci}, CodeRabbit={rev}', flush=True)
        if ci == 'issues':
            return 'fix', details + '\n' + feedback
        if rev in ('issues', 'blocked'):
            return 'fix' if rev == 'issues' else 'stop', details + '\n' + feedback
        if ci == 'clear' and rev == 'clear':
            return 'clear', details + '\n' + feedback
        time.sleep(POLL_SECONDS)
    return 'stop', 'CI/CodeRabbit did not finish or provide a verifiable success status before timeout'


def ensure_branch_protection(slug):
    """Fail closed unless active rules for main require PRs and CI validation.

    GitHub legacy protection and modern rulesets have separate REST endpoints.
    Query effective active rules rather than treating a legacy API 404 as unprotected.
    """
    rules = gh_json('api', f'repos/{slug}/rules/branches/main', '--paginate')
    if not isinstance(rules, list):
        raise RuntimeError('Could not inspect active branch rules')
    types = {r.get('type') for r in rules}
    if 'pull_request' not in types:
        raise RuntimeError('Active main rules must require a pull request before merging')
    required = [r for r in rules if r.get('type') == 'required_status_checks']
    checks = [c.get('context') for r in required
              for c in r.get('parameters', {}).get('required_status_checks', [])]
    if 'validate' not in checks:
        raise RuntimeError('Active main rules must require status check validate')
    if 'deletion' not in types:
        print('WARNING: Add restriction on main branch deletion in ruleset.', flush=True)
    if 'non_fast_forward' not in types:
        print('WARNING: Add restriction on force pushes in ruleset.', flush=True)
    print('Active rules verified: PR required; validate required.', flush=True)


def start(task_file):
    info = repo_info()
    if info['isPrivate']:
        raise RuntimeError('Configured for public-repository CodeRabbit free tier only')
    if info['defaultBranchRef']['name'] != 'main':
        raise RuntimeError('Default branch must be main')
    if sh('git', 'status', '--porcelain'):
        raise RuntimeError('Working tree must be clean; commit initial setup first')
    sh('git', 'switch', 'main')
    sh('git', 'pull', '--ff-only', 'origin', 'main', timeout=120)
    branch = 'ai/task-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    sh('git', 'switch', '-c', branch)
    return branch, info['nameWithOwner']


def loop(task_file, do_merge):
    task = Path(task_file).read_text().strip()
    if not task:
        raise ValueError('Task file must contain instructions')
    branch, slug = start(task_file)
    if do_merge:
        ensure_branch_protection(slug)
    owner, repo = slug.split('/', 1)
    feedback = ''
    pr_number = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f'\n=== Attempt {attempt}/{MAX_ATTEMPTS} ===', flush=True)
        try:
            generate(task, feedback)
        except Exception as ex:
            feedback = f'Generation failed: {ex}'
            print(feedback, flush=True)
            continue
        ok, output = local_tests()
        if not ok:
            feedback = 'Fix local test/syntax failure:\n' + output
            print(feedback[-2500:], flush=True)
            continue
        try:
            commit_push(branch, attempt)
        except Exception as ex:
            feedback = f'Commit/push failed: {ex}'
            print(feedback, flush=True)
            continue
        if pr_number is None:
            sh('gh', 'pr', 'create', '--base', 'main', '--head', branch,
               '--title', f'AI: {task[:65]}', '--body',
               'Automated local Ollama development. Review and CI are mandatory.\n\nTask:\n' + task[:2500])
            pr_number = gh_json('pr', 'view', branch, '--json', 'number')['number']
            print(f'PR: https://github.com/{slug}/pull/{pr_number}', flush=True)
        sha = git_head()
        # Explicit trigger covers newly-created OSS repositories with <10 stars.
        sh('gh', 'pr', 'comment', str(pr_number), '--body', '@coderabbitai full review')
        verdict, details = review_and_ci(owner, repo, pr_number, sha)
        if verdict == 'clear':
            if do_merge:
                # An independent protected-branch rule MUST require the CI check.
                # This command must never use --admin or --auto (which can bypass our local gate).
                sh('gh', 'pr', 'merge', str(pr_number), '--squash', '--delete-branch',
                   '--match-head-commit', sha, timeout=120)
                print('MERGED, protected-branch rules permitting.', flush=True)
            else:
                print('READY TO MERGE. Dry-run default: no merge performed.', flush=True)
            return
        if verdict == 'stop':
            raise RuntimeError('Stopped safely: ' + details)
        feedback = details
        print('Review/CI reported issues; requesting fix...', flush=True)
    if pr_number is None:
        raise RuntimeError('Max attempts exceeded before opening a PR. No PR exists. Inspect local generated app/ files.')
    raise RuntimeError(f'Max attempts exceeded. PR left open: https://github.com/{slug}/pull/{pr_number}')


def preflight():
    for binary in ('git', 'gh', 'ollama'):
        print(binary, sh('which', binary))
    print('Model:', MODEL)
    print('Ollama models:', sh('ollama', 'list')[:1000])
    print('GitHub login:', sh('gh', 'auth', 'status', check=False)[:1000] or 'See gh auth status')
    print('Repository:', repo_info()['nameWithOwner'])
    print('Git branch:', sh('git', 'branch', '--show-current'))
    print('Active main rules:', sh('gh', 'api', f'repos/{repo_info()["nameWithOwner"]}/rules/branches/main', check=False)[:1400])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    p = sub.add_parser('run')
    p.add_argument('task', help='Path to instructions text file')
    p.add_argument('--merge', action='store_true', help='Allow merge only after verified gates')
    args = parser.parse_args()
    try:
        if args.command == 'doctor':
            preflight()
        else:
            loop(args.task, args.merge)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
