# AI Code Review Setup

This repository has two AI-assisted workflows:

- `AI Code Review`: runs on pull requests, reads `.agents/skills/code-review-expert`, reviews the PR diff, and fails the check when P0/P1 issues are found.
- `AI Fix`: runs when a maintainer comments `/ai-fix` on a pull request, applies focused fixes to the PR branch, commits them, and pushes them back.

## Required GitHub Setup

1. Add repository secret:
   - Go to `Settings -> Secrets and variables -> Actions`.
   - Add one of these:
     - `ANTHROPIC_API_KEY` for a direct Anthropic API key.
     - `CLAUDE_CODE_OAUTH_TOKEN` for a Claude Code OAuth token.

2. Allow workflow write permissions:
   - Go to `Settings -> Actions -> General`.
   - Under `Workflow permissions`, select `Read and write permissions`.
   - Save the setting.

3. Enable branch protection:
   - Go to `Settings -> Branches`.
   - Add a rule for `main`.
   - Enable `Require a pull request before merging`.
   - Enable `Require status checks to pass before merging`.
   - Select the workflow checks for `Python CI / checks` and `AI Code Review / review`.

4. Use the workflow:
   - Open a pull request into `main`.
   - Wait for `Python CI` and `AI Code Review`.
   - If review finds blockers, comment `/ai-fix` on the PR.
   - Review the AI commit and wait for checks to run again.

## Notes

- Automatic fixes are intentionally disabled for forked pull requests.
- The AI review workflow does not edit code.
- The AI fix workflow is manually triggered by `/ai-fix` to avoid uncontrolled commit loops.
