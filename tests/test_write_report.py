import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from write_report import render_verdict_explanation


class RenderVerdictExplanationTest(unittest.TestCase):
    def test_mixed_verdict_lists_all_group_summaries(self):
        reviewer_data = {
            "is_mixed": True,
            "confidence": 0.91,
            "groups": [
                {"group_id": "R1", "summary": "Document the report stage"},
                {"group_id": "R2", "summary": "Add the report writer"},
            ],
        }

        self.assertEqual(
            render_verdict_explanation(reviewer_data),
            "Reviewer identified 2 final groups with confidence 0.91: "
            "R1 (Document the report stage); R2 (Add the report writer)",
        )

    def test_single_group_verdict_keeps_coherent_wording(self):
        reviewer_data = {
            "is_mixed": False,
            "confidence": 0.88,
            "groups": [{"group_id": "R1", "summary": "One coherent change"}],
        }

        self.assertEqual(
            render_verdict_explanation(reviewer_data),
            "Reviewer found one coherent final group with confidence 0.88: "
            "R1 (One coherent change)",
        )

    def test_long_group_list_is_explicitly_truncated(self):
        reviewer_data = {
            "is_mixed": True,
            "confidence": 0.75,
            "groups": [
                {"group_id": f"R{index}", "summary": f"Group {index}"}
                for index in range(1, 8)
            ],
        }

        self.assertEqual(
            render_verdict_explanation(reviewer_data),
            "Reviewer identified 7 final groups with confidence 0.75: "
            "R1 (Group 1); R2 (Group 2); R3 (Group 3); R4 (Group 4); "
            "R5 (Group 5); ... and 2 more groups",
        )


if __name__ == "__main__":
    unittest.main()
