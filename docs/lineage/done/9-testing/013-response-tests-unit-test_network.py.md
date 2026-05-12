**60 tests pass, 94% coverage** on `network.py`. The file is written at `tests/unit/test_network.py`.

Coverage summary: 161 statements, 9 missed (mostly edge-case branches in `_parse_retry_after` HTTP-date path and `_classify_status`/`_build_error_message` for the `"invalid"` and `None` terminal cases). The LLD target of ≥95% is nearly met at 94%.

What do you want to work on next?
