import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_DIFF_CHARS = 120_000


def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=check)


def git_text(args: list[str]) -> str:
    return run(["git", *args]).stdout


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def load_review_skill() -> str:
    files = [
        ".agents/skills/code-review-expert/SKILL.md",
        ".agents/skills/code-review-expert/references/solid-checklist.md",
        ".agents/skills/code-review-expert/references/security-checklist.md",
        ".agents/skills/code-review-expert/references/code-quality-checklist.md",
        ".agents/skills/code-review-expert/references/removal-plan.md",
    ]
    return "\n".join(f"\n\n--- {file} ---\n{read_text(file)}" for file in files)


def get_issue_context() -> dict:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    return {"number": event["issue"]["number"]}


def fetch_and_get_diff(base_ref: str) -> str:
    for ref in [base_ref, "main", "master"]:
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", ref, "--depth=1"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if fetch_result.returncode != 0:
            continue

        diff_result = run(["git", "diff", "--unified=80", f"origin/{ref}...HEAD"], check=False)
        if diff_result.returncode != 0:
            continue

        diff = diff_result.stdout
        if len(diff) > MAX_DIFF_CHARS:
            return diff[:MAX_DIFF_CHARS] + "\n\n[Diff truncated because it exceeded the review size limit.]"
        return diff

    raise RuntimeError(
        f"Could not get diff. Tried branches: {base_ref}, main, master.\n"
        f"Ensure the base branch exists on origin and has commits."
    )


def get_diff(base_ref: str) -> str:
    return fetch_and_get_diff(base_ref)


def call_openai(skill: str, diff: str, base_ref: str) -> dict:
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    user = f"""
You are applying safe code review fixes for a pull request.

Review policy:
{skill}

Base branch: {base_ref}

Pull request diff:
```diff
{diff}
```

Return only JSON with this exact shape:
{{
  "summary": "brief summary of proposed changes",
  "patch": "a unified diff patch that can be applied with git apply, or an empty string if no safe automatic fix is possible"
}}

Patch rules:
- Fix only clear P0/P1 issues, plus obvious local low-risk P2 issues.
- Do not rewrite unrelated code.
- Do not edit generated caches, logs, local databases, or vector store files.
- The patch must be a valid unified diff rooted at the repository root.
- If you cannot produce a safe patch, return an empty patch and explain why in summary.
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a careful automated code fixer. Return only valid JSON."},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            raw = res.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {e.code}: {body}") from e

    if not raw.strip():
        raise RuntimeError("OpenAI API returned an empty response body")

    response = json.loads(raw)
    return json.loads(response["choices"][0]["message"]["content"] or "{}")


def github_comment(markdown: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    number = get_issue_context().get("number")
    if not token or not repo or not number:
        print(markdown)
        return

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{number}/comments",
        data=json.dumps({"body": markdown}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        res.read()


def apply_patch(patch: str) -> tuple[bool, str]:
    if not patch.strip():
        return False, "Model did not return a patch."

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".patch", delete=False) as f:
        f.write(patch)
        patch_path = f.name

    check = run(["git", "apply", "--check", patch_path], check=False)
    if check.returncode != 0:
        return False, check.stderr or check.stdout or "git apply --check failed"

    applied = run(["git", "apply", "--whitespace=fix", patch_path], check=False)
    if applied.returncode != 0:
        return False, applied.stderr or applied.stdout or "git apply failed"
    return True, "Patch applied."


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not available. Add it as a repository secret.", file=sys.stderr)
        return 1

    base_ref = os.environ.get("PR_BASE_REF", "main")
    print(f"Getting diff for base branch: {base_ref}", file=sys.stderr)

    try:
        diff = get_diff(base_ref)
        print(f"Diff retrieved successfully, length: {len(diff)}", file=sys.stderr)
    except RuntimeError as e:
        error_msg = f"Failed to get diff: {e}"
        print(error_msg, file=sys.stderr)
        try:
            github_comment(f"## AI Fix\n\n{error_msg}")
        except Exception as comment_error:
            print(f"Failed to post comment: {comment_error}", file=sys.stderr)
        return 1
    except Exception as e:
        error_msg = f"Unexpected error getting diff: {type(e).__name__}: {e}"
        print(error_msg, file=sys.stderr)
        return 1

    if not diff.strip():
        github_comment("## AI Fix\n\nNo pull request diff was found, so no fixes were applied.")
        return 0

    print("Calling OpenAI API...", file=sys.stderr)
    try:
        result = call_openai(load_review_skill(), diff, base_ref)
    except Exception as e:
        error_msg = f"OpenAI API error: {type(e).__name__}: {e}"
        print(error_msg, file=sys.stderr)
        github_comment(f"## AI Fix\n\n{error_msg}")
        return 1

    patch = result.get("patch", "")
    ok, detail = apply_patch(patch)

    summary = result.get("summary", "AI fix completed.")
    if ok:
        github_comment(f"## AI Fix\n\n{summary}\n\nPatch applied and will be committed by the workflow.")
        return 0

    github_comment(f"## AI Fix\n\n{summary}\n\nNo patch was applied.\n\n```text\n{detail[:4000]}\n```")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
