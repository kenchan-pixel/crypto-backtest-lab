import pandas as pd

from forward_paper.taker_trade_tape_contract import aggregate_window, score


def _trades(offset_seconds=0):
    base = pd.Timestamp('2026-09-21T00:00:00Z') + pd.Timedelta(seconds=offset_seconds)
    rows = []
    for i in range(5):
        rows.append({'time': base + pd.Timedelta(minutes=i, seconds=10), 'quantity': 2.0, 'is_buyer_maker': False})
        rows.append({'time': base + pd.Timedelta(minutes=i, seconds=20), 'quantity': 1.0, 'is_buyer_maker': True})
    return pd.DataFrame(rows)


def test_aggregate_window_taker_direction_and_ratio():
    got = aggregate_window(_trades(), 0)
    row = got.loc[pd.Timestamp('2026-09-21T00:00:00Z')]
    assert row['buy'] == 10.0
    assert row['sell'] == 5.0
    assert row['tape_ratio'] == 2.0


def test_score_exact_nominal_window():
    idx = pd.date_range('2026-09-21T00:00:00Z', periods=250, freq='5min')
    rows = []
    for t in idx:
        rows.append({'time': t + pd.Timedelta(seconds=10), 'quantity': 2.0, 'is_buyer_maker': False})
        rows.append({'time': t + pd.Timedelta(seconds=20), 'quantity': 1.0, 'is_buyer_maker': True})
    metrics = pd.DataFrame({'archive_ratio': 2.0}, index=idx)
    got = score(metrics, pd.DataFrame(rows), 0)
    assert got['rows'] == 250
    assert got['max_abs_delta'] == 0.0
    assert got['exact_1e_10_rows'] == 250


def test_shifted_window_not_false_exact():
    idx = pd.date_range('2026-09-21T00:00:00Z', periods=250, freq='5min')
    rows = []
    for n, t in enumerate(idx):
        rows.append({'time': t + pd.Timedelta(seconds=2), 'quantity': float(2 + n % 3), 'is_buyer_maker': False})
        rows.append({'time': t + pd.Timedelta(seconds=4), 'quantity': 1.0, 'is_buyer_maker': True})
    metrics = pd.DataFrame({'archive_ratio': [float(2 + n % 3) for n in range(250)]}, index=idx)
    exact = score(metrics, pd.DataFrame(rows), 0)
    shifted = score(metrics, pd.DataFrame(rows), 5)
    assert exact['max_abs_delta'] == 0.0
    assert shifted['max_abs_delta'] > 0.0
