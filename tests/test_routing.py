import unittest

from otc_agent.routing import AuthorRouteIdentity, ModelRoute, ModelRouter, ModelTier, RoutingError


def route(*, model: str = "review-model", tier: ModelTier = ModelTier.STRONG) -> ModelRoute:
    return ModelRoute(
        role="reviewer",
        tier=tier,
        provider="copilot",
        model=model,
        endpoint="stdio:review",
    )


class RoutingTests(unittest.TestCase):
    def test_selects_independent_equal_strength_reviewer(self) -> None:
        reviewer = route()

        selected = ModelRouter(reviewer).select_reviewer(
            AuthorRouteIdentity(
                "author-model",
                ModelTier.STRONG,
                provider="copilot",
                endpoint="stdio:author",
            )
        )

        self.assertEqual(selected, reviewer)

    def test_rejects_weaker_reviewer(self) -> None:
        with self.assertRaises(RoutingError):
            ModelRouter(route(tier=ModelTier.FAST)).select_reviewer(
                AuthorRouteIdentity("author-model", ModelTier.STRONG)
            )

    def test_rejects_same_route(self) -> None:
        reviewer = route()

        with self.assertRaises(RoutingError):
            ModelRouter(reviewer).select_reviewer(
                AuthorRouteIdentity(reviewer.model, ModelTier.STRONG, reviewer.provider, reviewer.endpoint)
            )


if __name__ == "__main__":
    unittest.main()
