import json
import os
import subprocess
import sys
import tempfile
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


def get_diff(base_ref: str) -> str:
    subprocess.run(["git", "fetch", "origin", base_ref, "--depth=1"], cwd=ROOT, check=False)
    diff = git_text(["diff", "--unified=80", f"origin/{base_ref}...HEAD"])
    if len(diff) > MAX_DIFF_CHARS:
        return diff[:MAX_DIFF_CHARS] + "\n\n[Diff truncated because it exceeded the review size limit.]"
    return diff


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
    with urllib.request.urlopen(req, timeout=120) as res:
        response = json.loads(res.read().decode("utf-8"))

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
    diff = get_diff(base_ref)
    if not diff.strip():
        github_comment("## AI Fix\n\nNo pull request diff was found, so no fixes were applied.")
        return 0

    result = call_openai(load_review_skill(), diff, base_ref)
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
