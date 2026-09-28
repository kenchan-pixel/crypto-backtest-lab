import unittest
from decimal import Decimal

from forward_paper.account_ratio_precision_contract import (
    _component_ratio_interval,
    _reported_ratio_from_published_components,
)


class AccountRatioPrecisionContractTests(unittest.TestCase):
    def test_reported_ratio_matches_ratio_of_published_components(self):
        row = {
            "longAccount": "0.7005",
            "shortAccount": "0.2995",
            "longShortRatio": "2.3389",
        }
        self.assertEqual(
            _reported_ratio_from_published_components(row), Decimal("2.3389")
        )

    def test_component_rounding_interval_contains_plausible_higher_precision_ratio(self):
        row = {
            "longAccount": "0.7005",
            "shortAccount": "0.2995",
            "longShortRatio": "2.3389",
        }
        low, high = _component_ratio_interval(row)
        self.assertLess(low, Decimal("2.3389"))
        self.assertGreater(high, Decimal("2.3389"))
        self.assertLess(high - low, Decimal("0.002"))

    def test_component_rounding_interval_rejects_semantically_distant_ratio(self):
        row = {
            "longAccount": "0.5540",
            "shortAccount": "0.4460",
            "longShortRatio": "1.2422",
        }
        low, high = _component_ratio_interval(row)
        self.assertFalse(low <= Decimal("1.2500") <= high)


if __name__ == "__main__":
    unittest.main()
