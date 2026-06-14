# implicit.json contract

The implicit agent must write JSON with this structure:

```json
{
  "agent": "implicit-agent",
  "schema_version": 1,
  "groups": [
    {
      "group_id": "I1",
      "item_ids": ["C000001", "F000001"],
      "summary": "Short summary of this implicit group",
      "reason": "Why these items are semantically or contextually connected"
    }
  ],
  "ungrouped_item_ids": [],
  "warnings": []
}
```

Rules:

1. Every item id from input.json analysis_items must appear exactly once.
2. An item id may appear either in groups[].item_ids or in ungrouped_item_ids.
3. No unknown item ids are allowed.
4. No duplicate item ids are allowed.
5. Every group must have non-empty item_ids.
6. Every group must have non-empty summary.
7. Every group must have non-empty reason.
8. Use item_ids, not change_ids.
9. Return JSON only.
10. Do not write patch files.
11. Do not modify the repository.
