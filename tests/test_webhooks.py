import unittest

from otc_agent.state import WebhookEvent
from otc_agent.webhooks import process_webhook_once


class FakeWebhookStore:
    def __init__(self, event: WebhookEvent | None):
        self.event = event
        self.completed: tuple[str, dict[str, object]] | None = None
        self.failed: tuple[str, str, int, int] | None = None

    def claim_webhook(self, _worker_id: str) -> WebhookEvent | None:
        return self.event

    def complete_webhook(self, delivery_id: str, result: dict[str, object]) -> None:
        self.completed = (delivery_id, result)

    def fail_webhook(
        self,
        delivery_id: str,
        *,
        error: str,
        max_attempts: int,
        retry_seconds: int,
    ) -> str:
        self.failed = (delivery_id, error, max_attempts, retry_seconds)
        return "dead_letter" if self.event and self.event.attempts >= max_attempts else "queued"


class WebhookTests(unittest.TestCase):
    def test_processes_registered_webhook_handler(self) -> None:
        event = WebhookEvent("delivery-1", "pull_request_review", {"action": "submitted"}, 1)
        store = FakeWebhookStore(event)

        processed = process_webhook_once(
            store,
            worker_id="worker-1",
            handlers={"pull_request_review": lambda payload: {"action": payload["action"]}},
        )

        self.assertEqual(processed, event)
        self.assertEqual(store.completed, ("delivery-1", {"action": "submitted"}))
        self.assertIsNone(store.failed)

    def test_requeues_then_dead_letters_failed_webhook(self) -> None:
        event = WebhookEvent("delivery-2", "unknown", {}, 5)
        store = FakeWebhookStore(event)

        process_webhook_once(
            store,
            worker_id="worker-1",
            handlers={},
            max_attempts=5,
            retry_seconds=30,
        )

        self.assertIsNone(store.completed)
        assert store.failed is not None
        self.assertEqual(store.failed[0], "delivery-2")
        self.assertIn("KeyError", store.failed[1])
        self.assertEqual(store.failed[2:], (5, 30))
