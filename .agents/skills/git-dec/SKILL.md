---
name: git-dec
description: Run the local git decomposition prep command for a specific repository and commit. Use when the user invokes $git-dec, asks to prepare or collect git commit analysis inputs, asks to analyze a specific commit/hash/HEAD/HEAD~1 with git-dec, or asks for artifacts such as input.json and diff.patch for a repository commit.
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

## Arguments

- `--repo` is required. Use the repository path the user provides.
- `--commit` is required. Use the commit expression the user provides.
- `--out` is optional. Only pass it when the user explicitly asks for a custom output directory.

## User request mapping

- `$git-dec --repo /path/to/repo --commit HEAD` -> run `python3 main.py --repo /path/to/repo --commit HEAD`.
- `$git-dec --repo /path/to/repo --commit HEAD~1` -> run `python3 main.py --repo /path/to/repo --commit HEAD~1`.
- `$git-dec --repo /path/to/repo --commit 431f3e5fe5d20ba826f07178f94b9bcb20f3ec5b` -> run the same command with that hash.
- If the user says "последний коммит" or "текущий коммит", use `--commit HEAD`.
- If the user says "предпоследний коммит", use `--commit HEAD~1`.
- If the user says "коммит с хешем <hash>", use `--commit <hash>`.

## Workflow

1. Run the command from the project root that contains `main.py`.
2. Show the command you ran.
3. Show the JSON stdout from the command.
4. Briefly report the created `input.json` and `diff.patch` paths.

This prototype prepares commit data for later agents. It does not yet perform semantic analysis, patch generation, or report generation.

Do not modify files.
Do not create commits.

