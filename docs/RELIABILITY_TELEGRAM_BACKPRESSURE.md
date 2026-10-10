# Reliability: bounded Telegram ingress

Telegram can return multiple callbacks/messages in a single polling response.
Previously each accepted update spawned an unbounded daemon thread.

The bot now admits at most 24 concurrently running handler threads using
a bounded semaphore. Admission happens **before** advancing the Telegram
`update_id` offset. If capacity is exhausted, the current response batch
stops; its unaccepted update retains its ID for the next `getUpdates`
request rather than being skipped. Accepted callbacks use the same whitelist
and dispatch paths as before. Handler failures log an error and always
release the semaphore.

Tests: `tests/test_telegram_backpressure.py` plus
`tests/test_telegram_lifecycle.py`.

Remaining boundary: bot/process restarts during accepted-but-unfinished
handlers have the normal Telegram polling acknowledgment semantics; this is
not a transactional exactly-once delivery guarantee.
