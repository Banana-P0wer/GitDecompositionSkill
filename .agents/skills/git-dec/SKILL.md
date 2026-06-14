---
name: git-dec
description: Prepare and analyze a git commit with the local git decomposition prototype. Use when the user invokes $git-dec or asks to analyze, decompose, untangle, inspect, or prepare artifacts for a specific git commit.
---

# Git decomposition skill

This skill runs the local git_dec prototype for one repository commit.

## Safety rules

Do not modify source files in the analyzed repository.

Do not write patch files yet.

Do not create git commits.

Do not run destructive git commands such as reset, rebase, checkout, clean, or commit.

Only create or update files inside the .git-dec/<commit_sha>/ artifact directory unless the user explicitly asks for project-code changes.

## Inputs

The user may invoke the skill in forms like:

* $git-dec
* $git-dec HEAD
* $git-dec HEAD~1
* $git-dec 3
* $git-dec <commit-hash>
* $git-dec "part of commit subject"
* $git-dec --repo /path/to/repo --commit HEAD

Use the current Codex working directory as the default repository.

If the current directory is not inside a git repository and the user did not provide --repo, stop and ask for the repository path.

If the user provides a repository path, use it exactly.

If the user provides a commit target, pass it to main.py.

If the user provides no commit target, use HEAD.

If commit selection is ambiguous, show the candidates and ask the user to choose one. Do not guess.

## Main command

Run from the project root that contains this skill and main.py:
```bash
python3 main.py --repo <repo> --commit <commit>
```

Examples:
```bash
python3 main.py --repo . --commit HEAD
python3 main.py --repo . --commit HEAD~1
python3 main.py --repo /path/to/repo --commit <hash>
```

After running the command, read its JSON stdout.

Use stdout to find the output directory. It should be:
```text
<repo>/.git-dec/<resolved_commit_sha>/
```

The output directory should contain:
```text
input.json
diff.patch
```

## Explicit Agent stage

After input.json is created, spawn the Codex custom subagent named:

explicit-agent

Ask explicit-agent to:

1. Read <out_dir>/input.json.
2. Read references/explicit_agent.md.
3. Read references/explicit_agent_contract.md.
4. Group the commit analysis_items by explicit technical dependencies.
5. Write the result to <out_dir>/agents/explicit.json.
6. Use item_ids, not change_ids, in groups.
7. Include every analysis_items[].id exactly once.
8. Return JSON only.
9. Do not modify the analyzed repository.

The output file must be:
```text
<out_dir>/agents/explicit.json
```

The file must follow this shape:
```json
{
  "agent": "explicit-agent",
  "schema_version": 1,
  "groups": [
    {
      "group_id": "E1",
      "item_ids": ["C000001", "F000001"],
      "summary": "Short summary of this explicit group",
      "reason": "Why these items are explicitly connected"
    }
  ],
  "ungrouped_item_ids": [],
  "warnings": []
}
```

If an item has no explicit technical connection to another item, explicit-agent should put it in ungrouped_item_ids.

## Validate explicit-agent output

After explicit-agent writes explicit.json, run:
```bash
python3 validate_explicit.py --input <out_dir>/input.json --explicit <out_dir>/agents/explicit.json
```

If validation fails:

1. Read the validator error.
2. Ask the same explicit-agent subagent to fix <out_dir>/agents/explicit.json once.
3. Run validation again.
4. If validation still fails, stop and report the error.

Do not continue with an invalid explicit.json.

## Optional human-readable view

If validation succeeds and the user wants to inspect the grouping, run either:
```bash
python3 validate_explicit.py --input <out_dir>/input.json --explicit <out_dir>/agents/explicit.json --pretty
```

or:
```bash
python3 show_explicit.py --input <out_dir>/input.json --explicit <out_dir>/agents/explicit.json
```

Use the human-readable output to briefly summarize the explicit-agent result.

## Final response

In the final response to the user, report:

* selected repository;
* selected commit;
* created input.json path;
* created diff.patch path;
* created agents/explicit.json path;
* validation status;
* number of explicit groups;
* number of covered analysis items.

Keep the response short.

Mention clearly that this prototype currently runs only the prepare stage and the explicit-agent stage.