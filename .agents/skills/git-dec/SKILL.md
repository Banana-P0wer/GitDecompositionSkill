---
name: git-dec
description: Run the local git decomposition prep and explicit-agent stages for a specific repository and commit. Use when the user invokes $git-dec, including shorthand forms such as `$git-dec 3`, `$git-dec <hash>`, or `$git-dec "commit subject"`, asks to prepare or collect git commit analysis inputs, asks to analyze a specific commit/hash/HEAD/HEAD~1 with git-dec, or asks for artifacts such as input.json, diff.patch, and agents/explicit.json for a repository commit.
---

# Git decomposition prototype

Run the local entry point from the project root:

```bash
python3 main.py --repo <repo> --commit <commit>
```

`main.py` calls `prep.py` and creates:

```text
<repo>/.git-dec/<resolved_commit_sha>/
  input.json
  diff.patch
```

The full skill workflow then creates:

```text
<repo>/.git-dec/<resolved_commit_sha>/
  agents/explicit.json
```

## Arguments

- `--repo` is optional. When omitted, use the git repository from the current Codex working directory.
- `--commit` is required for explicit long-form calls. Shorthand calls may provide the commit as the first positional argument.
- `--out` is optional. Only pass it when the user explicitly asks for a custom output directory.

## Repository selection

- If the user provides `--repo`, use that path exactly.
- If the user does not provide `--repo`, determine the repository by running `git rev-parse --show-toplevel` in the current Codex working directory.
- Do not infer, search for, or choose a different repository when `--repo` is omitted.
- If the current working directory is not inside a git repository, stop and ask the user to provide `--repo` or restart/open Codex from the intended project directory. Say that it looks like Codex is not currently in a project repository, so the skill cannot safely choose one.

## User request mapping

- `$git-dec --repo /path/to/repo --commit HEAD` -> run `python3 main.py --repo /path/to/repo --commit HEAD`.
- `$git-dec --repo /path/to/repo --commit HEAD~1` -> run `python3 main.py --repo /path/to/repo --commit HEAD~1`.
- `$git-dec --repo /path/to/repo --commit 431f3e5fe5d20ba826f07178f94b9bcb20f3ec5b` -> run the same command with that hash.
- `$git-dec 1` -> use the current repository and `--commit HEAD`.
- `$git-dec 2` -> use the current repository and `--commit HEAD~1`.
- `$git-dec 3` -> use the current repository and `--commit HEAD~2`.
- In general, `$git-dec N` means the Nth commit from the end in the current repository, so use `HEAD~(N-1)`. `HEAD~3` is the fourth commit, not the third.
- `$git-dec 431f3e5fe5d20ba826f07178f94b9bcb20f3ec5b` -> use the current repository and that hash as `--commit`.
- `$git-dec "update git-dec"` -> search commit subjects in the current repository for `update git-dec`, then run the command for the matching commit hash.
- If the user says "последний коммит" or "текущий коммит", use `--commit HEAD`.
- If the user says "предпоследний коммит", use `--commit HEAD~1`.
- If the user says "коммит с хешем <hash>", use `--commit <hash>`.

## Commit subject lookup

Use subject lookup only when the shorthand argument is quoted text or clearly a commit title rather than a hash/ref.

1. Search the selected repository with `git log --format=%H%x00%s`.
2. Prefer an exact subject match, case-insensitive.
3. If there is no exact match, use a case-insensitive substring match.
4. If there is exactly one match, use its full hash as `--commit`.
5. If there are multiple matches, stop and show the matching short hashes and subjects; ask the user to choose one.
6. If there are no matches, stop and say no matching commit subject was found in the selected repository.

Do not guess a commit when subject lookup is ambiguous.

## Workflow

1. Determine the target repository using the rules above.
2. Resolve the requested commit expression from the explicit args or shorthand.
3. Run the command from the project root that contains `main.py`.
4. Show the command you ran.
5. Show the JSON stdout from the command.
6. Use the command stdout to find `<out_dir>/input.json`.
7. Run the Explicit Agent stage.
8. Show validator stdout.
9. If the user wants to inspect the grouping, show the pretty explicit-agent report.
10. Briefly report the created `input.json`, `diff.patch`, and `agents/explicit.json` paths.

## Explicit Agent stage

After `input.json` is created, run the Explicit Agent stage.

1. Read `<out_dir>/input.json`.
2. Use `references/explicit_agent.md` and `references/explicit_agent_contract.md`.
3. Create `<out_dir>/agents/explicit.json`.
4. The JSON must follow the explicit.json contract.
5. Run:

```bash
python3 validate_explicit.py --input <out_dir>/input.json --explicit <out_dir>/agents/explicit.json
```

6. If validation fails, fix `explicit.json` once and validate again.
7. Do not continue if validation still fails.

To validate and print a human-readable report, run:

```bash
python3 validate_explicit.py --input <out_dir>/input.json --explicit <out_dir>/agents/explicit.json --pretty
```

To only show the report after validation, run:

```bash
python3 show_explicit.py --input <out_dir>/input.json --explicit <out_dir>/agents/explicit.json
```

The explicit agent must group `analysis_items`, not only line-level `changes`.
Use `item_ids` in explicit groups. These ids may include both `C...` line changes and `F...` file events.

This prototype prepares commit data and explicit technical grouping for later agents. It does not yet perform patch generation or report generation.

Do not modify source files in the analyzed repository.
Do not write patch files.
Do not create commits.
