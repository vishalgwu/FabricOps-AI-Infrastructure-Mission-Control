# Phase 00 --- Audit the Existing Repository

## Goal

Understand the current GitHub repository and local folder before
changing anything.

## Instructions for the AI coding tool

-   Inspect the repository tree, current branch, Git status, README,
    existing code, and available environment.
-   Do not delete, rename, overwrite, or regenerate existing files.
-   Identify whether any prototype exists on another local folder or
    branch if the user provides access.
-   Report what is verified versus merely claimed.
-   If the repository is empty except for README, say so plainly.

## Tasks

1.  Open the existing repository in VS Code.
2.  Run `git status`, `git branch --all`, and `git remote -v`.
3.  Inspect the README and all tracked files.
4.  Record Python, Node, npm versions.
5.  Identify any existing prototype or uncommitted work.
6.  Create `docs/project/BASELINE_AUDIT.md` with verified findings.

## Acceptance

-   [x] Existing work is preserved.
-   [x] Repository state is documented.
-   [x] No application code has been generated yet. (true when the audit was done)
-   [x] The next implementation branch is agreed. (`main`)

## Suggested commit

`docs: record repository baseline audit`
