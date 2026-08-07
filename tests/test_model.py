import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from copilot.session_events import AssistantMessageData

from otc_agent.budget import Budget
from otc_agent.model import CopilotSDKModel, ModelError, model_from_environment


class FakeSession:
    def __init__(self) -> None:
        self.prompt = ""

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def send_and_wait(self, prompt: str, *, timeout: float) -> object:
        self.prompt = prompt
        return SimpleNamespace(
            data=AssistantMessageData(
                content='{"status":"ok"}',
                message_id="message-1",
                model="gpt-5",
                output_tokens=7,
            )
        )


class FakeClient:
    last_options: dict[str, object]
    last_session_options: dict[str, object]

    def __init__(self, **options: object) -> None:
        FakeClient.last_options = options
        self.session = FakeSession()

    async def __aenter__(self) -> "FakeClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def create_session(self, **options: object) -> FakeSession:
        FakeClient.last_session_options = options
        return self.session


class ModelTests(unittest.TestCase):
    def test_copilot_model_uses_isolated_tool_free_session(self) -> None:
        model = CopilotSDKModel("gpt-5", github_token="token", client_factory=FakeClient)
        budget = Budget(max_model_calls=1, max_input_tokens=100, max_output_tokens=20)

        result = model.generate_json(system="Return JSON.", user="Do it.", budget=budget)

        self.assertEqual(result.value, {"status": "ok"})
        self.assertEqual(result.provider, "copilot")
        self.assertEqual(result.endpoint, "stdio:bundled")
        self.assertEqual(FakeClient.last_options["mode"], "empty")
        self.assertEqual(FakeClient.last_session_options["available_tools"], [])
        self.assertFalse(FakeClient.last_session_options["enable_session_store"])

    def test_copilot_is_default_provider(self) -> None:
        with patch.dict(os.environ, {"OTC_MODEL_NAME": "gpt-5"}, clear=True):
            self.assertIsInstance(model_from_environment(), CopilotSDKModel)

    def test_rejects_unknown_provider(self) -> None:
        with patch.dict(os.environ, {"OTC_MODEL_PROVIDER": "unknown"}, clear=True):
            with self.assertRaises(ModelError):
                model_from_environment()


if __name__ == "__main__":
    unittest.main()
