from transcript_toolkit.core.cache import JsonlAppender, cache_key, iter_jsonl, latest_records


def test_cache_key_golden():
    # Golden values: if these change, the hashing scheme changed and every user cache
    # and recorded demo fingerprint silently invalidates. Do not update casually.
    assert cache_key("a", "b") == "3d64310d8364dfb1"
    assert cache_key("model-x", "medium", "low", "INSTRUCTIONS", "USER") == "c54f5e4e2585db2b"


def test_cache_key_order_sensitive():
    assert cache_key("a", "b") != cache_key("b", "a")
    assert cache_key("ab") != cache_key("a", "b")


def test_appender_roundtrip(tmp_path):
    path = tmp_path / "cache.jsonl"
    app = JsonlAppender(path)
    app.append({"key": "k1", "value": 1})
    app.append({"key": "k2", "value": "ü"})  # non-ascii preserved
    records = list(iter_jsonl(path))
    assert records == [{"key": "k1", "value": 1}, {"key": "k2", "value": "ü"}]


def test_iter_jsonl_missing_file(tmp_path):
    assert list(iter_jsonl(tmp_path / "absent.jsonl")) == []


def test_latest_records_last_wins(tmp_path):
    path = tmp_path / "cache.jsonl"
    app = JsonlAppender(path)
    app.append({"key": "k1", "value": "old"})
    app.append({"key": "k2", "value": "keep"})
    app.append({"key": "k1", "value": "new"})
    records = latest_records(path)
    assert records["k1"]["value"] == "new"
    assert records["k2"]["value"] == "keep"
