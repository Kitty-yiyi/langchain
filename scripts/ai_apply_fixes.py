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
    sections = []
    for file in files:
        try:
            content = read_text(file)
            sections.append(f"\n\n--- {file} ---\n{content}")
        except FileNotFoundError:
            print(f"Warning: {file} not found, skipping", file=sys.stderr)
    return "\n".join(sections)


def get_issue_context() -> dict:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    return {"number": event["issue"]["number"]}


def fetch_and_get_diff(base_ref: str) -> str:
    errors = []
    for ref in [base_ref, "main", "master"]:
        print(f"Trying to fetch origin/{ref}...", file=sys.stderr)
        fetch_result = subprocess.run(
            ["git", "fetch", "origin", ref, "--depth=1"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if fetch_result.returncode != 0:
            error = f"git fetch origin {ref} failed: {fetch_result.stderr or fetch_result.stdout}"
            print(error, file=sys.stderr)
            errors.append(error)
            continue

        print(f"Fetch succeeded, trying git diff origin/{ref} HEAD...", file=sys.stderr)
        diff_result = run(["git", "diff", "--unified=80", f"origin/{ref}", "HEAD"], check=False)
        if diff_result.returncode != 0:
            error = f"git diff origin/{ref} HEAD failed: {diff_result.stderr or diff_result.stdout}"
            print(error, file=sys.stderr)
            errors.append(error)
            continue

        diff = diff_result.stdout
        print(f"Diff succeeded, length: {len(diff)}", file=sys.stderr)
        if len(diff) > MAX_DIFF_CHARS:
            return diff[:MAX_DIFF_CHARS] + "\n\n[Diff truncated because it exceeded the review size limit.]"
        return diff

    raise RuntimeError(
        f"Could not get diff. Errors:\n" + "\n".join(errors)
    )


def get_diff(base_ref: str) -> str:
    return fetch_and_get_diff(base_ref)


def get_changed_files(diff: str) -> list[str]:
    files = []
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            parts = line.split(" ")
            if len(parts) >= 4:
                file_path = parts[2].replace("a/", "", 1)
                if file_path not in files:
                    files.append(file_path)
    return files


def call_openai(skill: str, diff: str, base_ref: str, changed_files: dict[str, str]) -> dict:
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    files_context = ""
    for file_path, content in changed_files.items():
        files_context += f"\n\n--- {file_path} ---\n```\n{content}\n```"

    user = f"""
You are an automated code fixer. Your job is to fix security vulnerabilities (P0) and critical bugs (P1).

Review policy:
{skill}

Base branch: {base_ref}

Changed files content:
{files_context}

Pull request diff:
```diff
{diff}
```

TASK: Fix P0/P1 issues by returning the COMPLETE FIXED FILE CONTENT.

Return JSON with this exact shape:
{{
  "summary": "brief description of what was fixed",
  "file_path": "path/to/fixed/file.py",
  "fixed_content": "the complete fixed file content, or empty string if no fix"
}}

RULES:
1. Return the COMPLETE file content, not a diff
2. Fix ONLY P0/P1 issues (security vulnerabilities like hardcoded secrets, critical bugs)
3. Keep all other code unchanged
4. If no safe fix is possible, return empty fixed_content and explain in summary
5. Only fix ONE file at a time

EXAMPLE - If you find hardcoded API key like:
API_SECRET_KEY = "sk-1234567890abcdef"

Fix it to:
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "")
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a careful automated code fixer. Return only valid JSON."},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }

    if not model.startswith("o"):
        payload["temperature"] = 0.1

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    print(f"Sending request to {base_url}/chat/completions with model {model}", file=sys.stderr)
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            raw = res.read().decode("utf-8")
        print(f"API response received, length: {len(raw)}", file=sys.stderr)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {e.code}: {body}") from e
    except Exception as e:
        raise RuntimeError(f"Request failed: {type(e).__name__}: {e}") from e

    if not raw.strip():
        raise RuntimeError("OpenAI API returned an empty response body")

    response = json.loads(raw)
    content = response.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    return json.loads(content or "{}")


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

    print(f"Patch content:\n{patch}", file=sys.stderr)

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

    changed_file_paths = get_changed_files(diff)
    print(f"Changed files: {changed_file_paths}", file=sys.stderr)

    changed_files = {}
    for file_path in changed_file_paths[:5]:
        try:
            content = read_text(file_path)
            changed_files[file_path] = content
            print(f"Read file: {file_path}, length: {len(content)}", file=sys.stderr)
        except Exception as e:
            print(f"Failed to read {file_path}: {e}", file=sys.stderr)

    if not changed_files:
        github_comment("## AI Fix\n\nNo readable files found in the diff.")
        return 0

    print("Calling OpenAI API...", file=sys.stderr)
    try:
        print("Loading review skill...", file=sys.stderr)
        skill = load_review_skill()
        print(f"Review skill loaded, length: {len(skill)}", file=sys.stderr)
        result = call_openai(skill, diff, base_ref, changed_files)
        print(f"OpenAI API call succeeded, result keys: {list(result.keys())}", file=sys.stderr)
    except Exception as e:
        error_msg = f"OpenAI API error: {type(e).__name__}: {e}"
        print(error_msg, file=sys.stderr)
        github_comment(f"## AI Fix\n\n{error_msg}")
        return 1

    summary = result.get("summary", "AI fix completed.")
    file_path = result.get("file_path", "")
    fixed_content = result.get("fixed_content", "")

    if not file_path or not fixed_content:
        github_comment(f"## AI Fix\n\n{summary}\n\nNo file was modified.")
        return 0

    print(f"Writing fix to {file_path}", file=sys.stderr)
    try:
        target_path = ROOT / file_path
        if not target_path.exists():
            github_comment(f"## AI Fix\n\nError: File {file_path} does not exist.")
            return 1

        target_path.write_text(fixed_content, encoding="utf-8")
        print(f"Successfully wrote fix to {file_path}", file=sys.stderr)
        github_comment(f"## AI Fix\n\n{summary}\n\nFixed file: `{file_path}`\n\nChanges will be committed by the workflow.")
        return 0
    except Exception as e:
        error_msg = f"Failed to write file: {type(e).__name__}: {e}"
        print(error_msg, file=sys.stderr)
        github_comment(f"## AI Fix\n\n{error_msg}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
