import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_DIFF_CHARS = 120_000


def run_git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace")


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
        sections.append(f"\n\n--- {file} ---\n{read_text(file)}")
    return "\n".join(sections)


def get_pr_context() -> dict:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise RuntimeError("GITHUB_EVENT_PATH is not set")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    return {
        "number": pr.get("number") or event.get("number"),
        "base_ref": pr.get("base", {}).get("ref") or os.environ.get("GITHUB_BASE_REF", "main"),
        "head_ref": pr.get("head", {}).get("ref") or os.environ.get("GITHUB_HEAD_REF", ""),
    }


def get_diff(base_ref: str) -> str:
    subprocess.run(["git", "fetch", "origin", base_ref, "--depth=1"], cwd=ROOT, check=False)
    diff = run_git(["diff", "--unified=80", f"origin/{base_ref}...HEAD"])
    if len(diff) > MAX_DIFF_CHARS:
        return diff[:MAX_DIFF_CHARS] + "\n\n[Diff truncated because it exceeded the review size limit.]"
    return diff


def call_openai(skill: str, diff: str, context: dict) -> dict:
    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    system = (
        "You are a senior code reviewer. Review only the supplied pull request diff. "
        "Use the provided skill/checklists as the review policy. Return only valid JSON."
    )
    user = f"""
Pull request context:
- number: {context.get("number")}
- base_ref: {context.get("base_ref")}
- head_ref: {context.get("head_ref")}

Review policy:
{skill}

Pull request diff:
```diff
{diff}
```

Return JSON with this exact shape:
{{
  "blockers_found": boolean,
  "max_severity": "P0" | "P1" | "P2" | "P3" | "NONE",
  "summary": "short summary",
  "markdown": "GitHub-flavored Markdown review comment. Include findings grouped by P0-P3. If there are no findings, say what was checked and residual risk."
}}

Set blockers_found to true only when there are P0 or P1 findings that should block merge.
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as res:
        response = json.loads(res.read().decode("utf-8"))

    content = response["choices"][0]["message"]["content"] or "{}"
    return json.loads(content)


def github_comment(markdown: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    context = get_pr_context()
    number = context.get("number")

    if not token or not repo or not number:
        print(markdown)
        return

    url = f"https://api.github.com/repos/{repo}/issues/{number}/comments"
    payload = json.dumps({"body": markdown}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
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


def write_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(markdown, encoding="utf-8")


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not available. Add it as a repository secret.", file=sys.stderr)
        return 1

    context = get_pr_context()
    skill = load_review_skill()
    diff = get_diff(context["base_ref"])
    if not diff.strip():
        markdown = "## AI Code Review\n\nNo pull request diff was found to review."
        github_comment(markdown)
        write_summary(markdown)
        return 0

    result = call_openai(skill, diff, context)
    markdown = result.get("markdown") or result.get("summary") or "AI review completed."
    markdown = f"## AI Code Review\n\n{markdown}"
    github_comment(markdown)
    write_summary(markdown)

    if bool(result.get("blockers_found")):
        print("AI review found blocking P0/P1 issues.", file=sys.stderr)
        print(result.get("summary", ""), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
