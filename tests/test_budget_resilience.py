import unittest

from otc_agent.budget import Budget, BudgetExceeded
from otc_agent.resilience import Dependency, FailureAction, RetryPolicy, decide_failure, retry


class BudgetAndResilienceTests(unittest.TestCase):
    def test_budget_is_charged_atomically(self) -> None:
        budget = Budget(max_model_calls=1, max_input_tokens=10, max_output_tokens=10, max_cost_usd=1)
        budget.charge(input_tokens=5, output_tokens=2, cost_usd=0.1)
        with self.assertRaises(BudgetExceeded):
            budget.charge(input_tokens=1, output_tokens=1, cost_usd=0.1)
        self.assertEqual(budget.model_calls, 1)

    def test_retry_only_as_policy_allows(self) -> None:
        calls = 0

        def flaky() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TimeoutError("temporary")
            return "ok"

        result = retry(
            flaky,
            policy=RetryPolicy(attempts=3, base_delay_seconds=0),
            retryable=lambda exc: isinstance(exc, TimeoutError),
            sleep=lambda _: None,
        )
        self.assertEqual(result, "ok")
        self.assertEqual(calls, 3)

    def test_non_retryable_error_is_not_repeated(self) -> None:
        calls = 0

        def fail() -> None:
            nonlocal calls
            calls += 1
            raise ValueError("bad input")

        with self.assertRaises(ValueError):
            retry(fail, policy=RetryPolicy(), retryable=lambda exc: isinstance(exc, TimeoutError), sleep=lambda _: None)
        self.assertEqual(calls, 1)

    def test_dependency_failures_fail_closed(self) -> None:
        self.assertEqual(
            decide_failure(Dependency.RETRIEVAL, "timeout", attempt=3, verified_snapshot=True),
            FailureAction.USE_VERIFIED_SNAPSHOT,
        )
        self.assertEqual(
            decide_failure(Dependency.RETRIEVAL, "timeout", attempt=3, verified_snapshot=False),
            FailureAction.BLOCK,
        )
        self.assertEqual(
            decide_failure(Dependency.TOOL, "unknown_write_result", attempt=1),
            FailureAction.RECONCILE,
        )
        self.assertEqual(
            decide_failure(Dependency.MODEL, "authorization", attempt=1),
            FailureAction.BLOCK,
        )


if __name__ == "__main__":
    unittest.main()
