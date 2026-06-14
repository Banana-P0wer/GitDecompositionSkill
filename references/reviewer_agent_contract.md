# reviewer.json contract

The reviewer agent must write JSON with this structure:

```json
{
  "agent": "reviewer-agent",
  "schema_version": 1,
  "is_mixed": true,
  "confidence": 0.82,
  "groups": [
    {
      "group_id": "R1",
      "item_ids": ["C000001", "F000001"],
      "summary": "Final group summary",
      "why": "Why these items belong together in the final decomposition",
      "evidence": {
        "explicit": "What explicit-agent suggested for these items",
        "implicit": "What implicit-agent suggested for these items"
      }
    }
  ],
  "disagreements_resolved": [
    {
      "item_ids": ["C000001", "F000001"],
      "explicit_position": "How explicit-agent grouped or separated these items",
      "implicit_position": "How implicit-agent grouped or separated these items",
      "decision": "Final reviewer decision",
      "reason": "Why reviewer chose this decision"
    }
  ],
  "warnings": []
}
```

Rules:

1. Every item id from input.json analysis_items must appear exactly once in groups[].item_ids.
2. Do not use ungrouped_item_ids.
3. No unknown item ids are allowed.
4. No duplicate item ids are allowed.
5. Every group must have non-empty item_ids.
6. Every group must have non-empty summary.
7. Every group must have non-empty why.
8. Every group must have non-empty evidence.
9. evidence must be a JSON object.
10. is_mixed must be a boolean.
11. confidence must be a number from 0.0 to 1.0.
12. If final groups count is greater than 1, is_mixed should be true.
13. If final groups count is 1, is_mixed should usually be false.
14. Return JSON only.
15. Do not write patch files.
16. Do not modify the repository.
