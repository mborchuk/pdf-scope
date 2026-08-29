# Repository configuration

Half of a repository's configuration lives outside the repository: merge
strategies, security features, Actions policy, labels. That half is invisible in
a clone and easy to lose. This page is the record of what is set, why, and what
is deliberately still missing — including the exact commands to reproduce it.

- [What is configured on GitHub](#what-is-configured-on-github)
- [What is configured in the repository](#what-is-configured-in-the-repository)
- [Not available while the repository is private on GitHub Free](#not-available-while-the-repository-is-private-on-github-free)
- [Checklist for going public](#checklist-for-going-public)
- [Reapplying the settings](#reapplying-the-settings)

The repository is **private**: `github.com/mborchuk/pdf-scope`. Badges and links
in `README.md` resolve only for accounts with access until that changes.

## What is configured on GitHub

| Setting | Value | Why |
| --- | --- | --- |
| Description, topics | Set from the project description; ten topics | The only discovery metadata GitHub has |
| Issues | On | Bug reports, with the two templates in `.github/ISSUE_TEMPLATE/` |
| Wiki, Projects | Off | Documentation lives in `docs/`; a wiki would be a second, stale copy |
| Merge methods | **Squash only** — merge commits and rebase merges off | Every pull request becomes one commit on `main`, so history reads as a list of changes |
| Squash commit title | Pull request title | Predictable subjects; Dependabot's titles are already in the right shape |
| Squash commit body | The commits of the branch | Keeps the reasoning that was written per commit |
| Delete head branch on merge | On | Dependabot and feature branches do not accumulate |
| Always suggest updating branches | On | A stale branch can be brought forward without a local checkout |
| Dependabot alerts | On | GitHub matches the dependency graph against its advisory database |
| Dependabot security updates | On | A vulnerable pin gets a pull request without waiting for the weekly run |
| Actions: allowed actions | GitHub-owned and verified creators only | An unvetted third-party action can read anything the workflow can |
| Actions: default token | Read-only, cannot approve pull requests | Nothing in CI writes to the repository |
| Labels | `dependencies`, `python`, `ci`, `docker`, `security`, `performance` added to the defaults | Dependabot can only apply labels that already exist — the ones in `dependabot.yml` were being dropped silently before |

## What is configured in the repository

| File | What it does |
| --- | --- |
| `.github/workflows/ci.yml` | Lint, tests on five Python versions and three operating systems, a server smoke test, and a container build that runs the image's own health check |
| `.github/scripts/check_links.py` | Every relative Markdown link and heading anchor resolves. Runs in the lint job and in `make lint`, offline |
| `.github/workflows/audit.yml` | `pip-audit` against the pinned dependency set: weekly, on pull requests that touch the pins, and on demand |
| `.github/dependabot.yml` | Weekly updates for pip, GitHub Actions and the Dockerfile base image, grouped so routine bumps arrive as one pull request per area |
| `.github/CODEOWNERS` | One owner for every path; review requests are automatic |
| `.github/rulesets/main.json` | The branch ruleset to apply once the plan allows it (see below) |
| `.github/ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md` | Issue forms, a security contact link, and the pull-request checklist |
| `.gitattributes` | LF everywhere, binary formats marked, prose excluded from language statistics |
| `.pre-commit-config.yaml` | Optional local hooks: Ruff plus hygiene checks, and a hook that refuses committed PDFs. `make hooks` installs them |
| `requirements-audit.txt` | The `pip-audit` pin, kept out of the development set |
| `tests/test_packaging.py` | Fails if `requirements*.txt` and `pyproject.toml` disagree, or if anything is unpinned |

Actions in workflows are pinned to a **commit SHA** with the release in a
trailing comment:

```yaml
- uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

A tag can be moved to different code; a SHA cannot. Dependabot updates both the
SHA and the comment.

## Not available while the repository is private on GitHub Free

These are plan limits, not decisions. Each was attempted and refused.

| Feature | What it would add | Availability |
| --- | --- | --- |
| Rulesets / branch protection | No direct pushes to `main`, required status checks, linear history | Free for **public** repositories; for a private one it needs GitHub Pro. The API answers `403 Upgrade to GitHub Pro or make this repository public` |
| Auto-merge | Merge a pull request as soon as checks pass | Silently stays off on this plan; it belongs with required checks anyway |
| Secret scanning and push protection | Blocks a committed credential at push time | Public repositories, or Secret Protection on a paid plan |
| Code scanning (CodeQL) | Static analysis of the Python and JavaScript | Public repositories, or GitHub Advanced Security |
| Private vulnerability reporting | The "Report a vulnerability" form `SECURITY.md` points at | Public repositories only |
| `dependency-review-action` | Blocks a pull request that introduces a vulnerable dependency | Needs the dependency graph on a public repository or GHAS |

Until then, the substitutes in place are: `pip-audit` on a schedule (covers the
same advisory data as Dependabot alerts, and fails loudly), the pre-commit
`detect-private-key` hook, and `make check`.

## Checklist for going public

Do these in order. The first two only need the current branch merged.

1. **Merge the branch that pins actions to SHAs**, then require SHA pinning:

   ```bash
   gh api -X PUT repos/mborchuk/pdf-scope/actions/permissions \
     -F enabled=true -f allowed_actions=selected -F sha_pinning_required=true
   ```

   Enabling this before the pins are on the default branch would fail every
   workflow that still refers to a tag.

2. **Point the local remote at the current name** (GitHub redirects the old one,
   so this is tidiness rather than repair):

   ```bash
   git remote set-url origin git@github.com:mborchuk/pdf-scope.git
   ```

3. **Read the repository as a stranger would** before flipping visibility:
   no absolute local paths, no customer file names, no PDFs in the history
   (`git log --diff-filter=A --name-only -- '*.pdf'` should print nothing), and
   `.workspace/` never tracked.

4. **Make it public**, then apply the branch ruleset:

   ```bash
   gh repo edit mborchuk/pdf-scope --visibility public --accept-visibility-change-consequences
   gh api -X POST repos/mborchuk/pdf-scope/rulesets --input .github/rulesets/main.json
   ```

   The ruleset requires a pull request for `main`, requires the four named
   checks, forbids force-pushes and deletion, and keeps history linear. It
   asks for **zero** approvals — a single maintainer cannot approve their own
   pull request — and lets the repository admin bypass for an emergency. Raise
   `required_approving_review_count` to 1 as soon as there is a second
   maintainer, and set `require_code_owner_review` to `true` with it.

5. **Turn on the security features that become free**:

   ```bash
   gh api -X PATCH repos/mborchuk/pdf-scope \
     -f 'security_and_analysis[secret_scanning][status]=enabled' \
     -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
   ```

   Then enable private vulnerability reporting (Settings → Code security), which
   is what the `SECURITY.md` reporting link and the issue-template contact link
   already point to.

6. **Add code scanning.** Default setup is one click in Settings → Code
   security; it covers Python and JavaScript here. Prefer it over a committed
   CodeQL workflow: there is nothing to maintain.

7. **Consider `dependency-review-action`** on pull requests once the dependency
   graph is public, and drop the `pip-audit` pull-request trigger if it turns out
   to duplicate it. Keep the scheduled run either way.

8. **First release.** `docs/development.md#release-process` is the manual
   sequence. If releases become frequent, automate the build and the release
   notes with a tag-triggered workflow using trusted publishing to PyPI, so no
   token has to be stored.

## Reapplying the settings

Everything on GitHub's side, in the order it was applied. Safe to re-run.

```bash
R=mborchuk/pdf-scope

gh repo edit $R \
  --description "Inspect PDF files: the object model, page contents, text, images, vector paths and coordinates, in a local web UI." \
  --enable-issues=true --enable-wiki=false --enable-projects=false \
  --enable-squash-merge=true --enable-merge-commit=false --enable-rebase-merge=false \
  --delete-branch-on-merge=true --allow-update-branch=true \
  --add-topic pdf --add-topic pymupdf --add-topic pdf-analysis \
  --add-topic pdf-extraction --add-topic pdf-parser --add-topic document-analysis \
  --add-topic fastapi --add-topic python --add-topic self-hosted --add-topic forensics

gh api -X PATCH repos/$R \
  -f squash_merge_commit_title=PR_TITLE \
  -f squash_merge_commit_message=COMMIT_MESSAGES

gh api -X PUT repos/$R/vulnerability-alerts
gh api -X PUT repos/$R/automated-security-fixes

gh api -X PUT repos/$R/actions/permissions -F enabled=true -f allowed_actions=selected
gh api -X PUT repos/$R/actions/permissions/selected-actions \
  -F github_owned_allowed=true -F verified_allowed=true

for spec in \
  "dependencies:0366d6:Dependency updates" \
  "python:3572a5:Python dependencies or code" \
  "ci:5319e7:Continuous integration and workflows" \
  "docker:0db7ed:Container image" \
  "security:d93f0b:Security-relevant change or report" \
  "performance:fbca04:Speed or memory"; do
  name=${spec%%:*}; rest=${spec#*:}; color=${rest%%:*}; text=${rest#*:}
  gh label create "$name" --color "$color" --description "$text" -R $R \
    || gh label edit "$name" --color "$color" --description "$text" -R $R
done
```

Read the result back with:

```bash
gh api repos/mborchuk/pdf-scope --jq '{visibility, description, topics,
  allow_squash_merge, allow_merge_commit, allow_rebase_merge,
  delete_branch_on_merge, allow_update_branch, squash_merge_commit_title}'
gh api repos/mborchuk/pdf-scope/actions/permissions
gh api repos/mborchuk/pdf-scope/vulnerability-alerts -i | head -1   # 204 = on
gh api repos/mborchuk/pdf-scope/automated-security-fixes
```
