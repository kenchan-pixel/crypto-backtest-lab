import json
from pathlib import Path

import forward_paper.receipt2_pipeline as receipt2


def test_receipt2_relabels_only_commissioning_ordinal(monkeypatch, tmp_path):
    inner = {
        "passed": True,
        "qualifying_current_receipt": True,
        "model_sha256": receipt2.MODEL_SHA,
        "paper_trades_created": 0,
        "performance_started": False,
        "order_account_endpoints_used": False,
        "raw_source_values_rewritten": False,
        "current_cut_candidate_count": 0,
        "fresh_blob_checks": {"open_interest": {"sha256": "abc"}},
    }

    def fake_run(base_dir, fresh_dir, macro_capture, out_path, qualifying_current=False):
        assert qualifying_current is True
        Path(out_path).write_text(json.dumps(inner))
        return dict(inner)

    monkeypatch.setattr(receipt2, "run_extension", fake_run)
    out = tmp_path / "receipt2.json"
    r = receipt2.run("base", "fresh", "macro", out)
    saved = json.loads(out.read_text())
    assert r == saved
    assert r["qualifying_current_receipt_number"] == 2
    assert r["gate_effect"].startswith("Receipt 2 of 2")
    assert r["current_cut_candidate_count"] == inner["current_cut_candidate_count"]
    assert r["fresh_blob_checks"] == inner["fresh_blob_checks"]
    assert not Path(str(out) + ".inner").exists()
