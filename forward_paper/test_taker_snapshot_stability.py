from decimal import Decimal

from forward_paper.taker_snapshot_stability import compare_snapshots, volume_ratio_interval


def _row(ratio="1.2500", buy="125.0000", sell="100.0000"):
    return {"buySellRatio": ratio, "buyVol": buy, "sellVol": sell, "timestamp": 1}


def test_compare_snapshots_requires_exact_public_values():
    old = {i: {**_row(), "timestamp": i} for i in range(10)}
    new = {i: {**_row(), "timestamp": i} for i in range(10)}
    got = compare_snapshots(old, new)
    assert got["stable"] is True
    assert got["rows"] == 10
    assert got["exact_match_cells"] == 30
    assert got["mismatch_cells"] == 0


def test_compare_snapshots_detects_one_changed_field():
    old = {i: {**_row(), "timestamp": i} for i in range(10)}
    new = {i: {**_row(), "timestamp": i} for i in range(10)}
    new[5]["buyVol"] = "125.0001"
    got = compare_snapshots(old, new)
    assert got["stable"] is False
    assert got["mismatch_cells"] == 1
    assert got["mismatch_examples"][0]["field"] == "buyVol"


def test_volume_ratio_interval_is_precision_derived():
    lo, hi = volume_ratio_interval("125.0000", "100.0000")
    assert lo < Decimal("1.25") < hi
    # Both inputs expose four decimal places, so the conservative interval is
    # narrow and mechanically derived from +/- half an LSU for each volume.
    assert Decimal("0") < (hi - lo) < Decimal("0.000003")
