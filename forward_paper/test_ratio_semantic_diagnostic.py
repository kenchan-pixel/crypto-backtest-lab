import unittest

import pandas as pd

from forward_paper.ratio_semantic_diagnostic import (
    _candidate_sort_key,
    _score_candidate,
    _transforms,
)


class RatioSemanticDiagnosticTests(unittest.TestCase):
    def test_taker_transforms_keep_direct_and_volume_semantics_separate(self):
        row = {
            "buySellRatio": "2.0000",
            "buyVol": "10.0000",
            "sellVol": "5.0000",
        }
        got = _transforms("taker", row)
        self.assertEqual(got["direct_ratio"], 2.0)
        self.assertEqual(got["reciprocal_ratio"], 0.5)
        self.assertEqual(got["buy_volume_over_sell_volume"], 2.0)
        self.assertEqual(got["sell_volume_over_buy_volume"], 0.5)

    def test_offset_scoring_finds_archive_plus_five_mapping(self):
        archive = pd.DataFrame(
            {"count_long_short_ratio": [1.25, 0.75]},
            index=pd.to_datetime([
                "2026-09-20T23:40:00Z",
                "2026-09-20T23:45:00Z",
            ]),
        )
        rows = [
            {"timestamp": 1789947900000, "longShortRatio": "1.2500"},
            {"timestamp": 1789948200000, "longShortRatio": "0.7500"},
        ]
        plus5 = _score_candidate(
            archive, rows, "global_accounts", "direct_ratio", 5
        )
        zero = _score_candidate(
            archive, rows, "global_accounts", "direct_ratio", 0
        )
        self.assertEqual(plus5["within_half_lsu"], 2)
        self.assertEqual(plus5["match_rate"], 1.0)
        self.assertLess(zero["match_rate"], 1.0)
        self.assertGreater(
            _candidate_sort_key(("plus5", plus5)),
            _candidate_sort_key(("zero", zero)),
        )


if __name__ == "__main__":
    unittest.main()
