from __future__ import annotations

from collections.abc import Callable

from .state import PostgresStateStore, WebhookEvent


WebhookHandler = Callable[[dict[str, object]], dict[str, object]]


def process_webhook_once(
    store: PostgresStateStore,
    *,
    worker_id: str,
    handlers: dict[str, WebhookHandler],
    max_attempts: int = 5,
    retry_seconds: int = 60,
) -> WebhookEvent | None:
    event = store.claim_webhook(worker_id)
    if event is None:
        return None
    try:
        handler = handlers[event.event_type]
        result = handler(event.payload)
        if not isinstance(result, dict):
            raise TypeError("webhook handler result must be an object")
    except Exception as exc:
        store.fail_webhook(
            event.delivery_id,
            error=f"{type(exc).__name__}: {exc}",
            max_attempts=max_attempts,
            retry_seconds=retry_seconds,
        )
        return event
    store.complete_webhook(event.delivery_id, result)
    return event
