import json
from pathlib import Path
import pytest
from forward_paper.persisted_pipeline import load_snapshot,git_blob_sha1

SNAP='forward_paper/inputs/connected_binance_full_20260922T072853HKT'

def test_full_connected_snapshot_is_hash_locked_and_complete():
    manifest,observed,rows,checks=load_snapshot(SNAP)
    assert observed.isoformat()=='2026-09-21T23:42:43+00:00'
    assert manifest['gate_promotion'] is False
    assert all(len(rows[k])==283 for k in ['open_interest','top_accounts','top_positions','all_accounts','taker'])
    assert len(rows['funding'])==100
    assert all(len(checks[k]['sha256'])==64 for k in checks)
    assert manifest['archive_overlap_expected']['value_level_overlap_validated'] is False

def test_git_blob_hash_detects_content_change(tmp_path):
    original=Path(SNAP+'/open_interest.json').read_bytes()
    assert git_blob_sha1(original)==json.loads(Path(SNAP+'/manifest.json').read_text())['sources']['open_interest']['git_blob_sha1']
    tampered=original+b'\n'
    assert git_blob_sha1(tampered)!=git_blob_sha1(original)
