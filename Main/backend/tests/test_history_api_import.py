from app.services.history_import import (
    _entry_to_row,
    _source_key,
    api_source_label,
    flatten_round_entries,
)


def test_flatten_portfolio_rounds_payload():
    payload = {
        "portfolio_mode": True,
        "rounds": [
            {
                "round_id": "2026-07-02T17:52:00+00:00",
                "region": "chr21:14558002-19558002",
                "instances": {
                    "newgatk": {
                        "combined_final": 0.93,
                        "tool": "gatk",
                        "config_snapshot": {"pcr_indel_model": "NONE"},
                        "scored_at": "2026-07-02T19:10:21.838571+00:00",
                    }
                },
            }
        ],
    }

    entries = flatten_round_entries(payload)
    assert len(entries) == 1
    assert entries[0]["round_id"] == "2026-07-02T17:52:00+00:00"
    assert entries[0]["region"] == "chr21:14558002-19558002"
    assert entries[0]["instance_id"] == "newgatk"
    assert entries[0]["combined_final"] == 0.93


def test_entry_to_row_includes_instance_in_source_key():
    entry = {
        "round_id": "2026-07-02T17:52:00+00:00",
        "region": "chr21:14558002-19558002",
        "combined_final": 0.93,
        "tool": "gatk",
        "instance_id": "newgatk",
        "config_snapshot": {"pcr_indel_model": "NONE"},
    }
    label = api_source_label("http://192.168.131.16:7860/api/rounds")
    row = _entry_to_row(label, entry)
    assert row is not None
    assert row.window == "chr21:14558002-19558002"
    assert row.score == 0.93
    assert row.source_key == _source_key(label, entry)
    assert row.source_key == "gatk:2026-07-02T17:52:00+00:00:chr21:14558002-19558002:newgatk"
