import os
import unittest
from unittest.mock import patch

from otc_agent.routing import (
    author_route_from_environment,
    AuthorRouteIdentity,
    ModelRoute,
    ModelRouter,
    ModelTier,
    RoutingError,
)


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

    def test_selects_tiered_author_routes_with_strong_fallback(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OTC_FAST_MODEL_NAME": "fast-model",
                "OTC_STRONG_MODEL_NAME": "strong-model",
            },
            clear=True,
        ):
            fast = author_route_from_environment(ModelTier.FAST)
            strong = author_route_from_environment(ModelTier.STRONG)

        self.assertEqual((fast.tier, fast.model), (ModelTier.FAST, "fast-model"))
        self.assertEqual((strong.tier, strong.model), (ModelTier.STRONG, "strong-model"))

        with patch.dict(os.environ, {"OTC_STRONG_MODEL_NAME": "strong-model"}, clear=True):
            fallback = author_route_from_environment(ModelTier.FAST)
        self.assertEqual((fallback.tier, fallback.model), (ModelTier.STRONG, "strong-model"))

    def test_strong_route_never_falls_back_to_fast(self) -> None:
        with patch.dict(os.environ, {"OTC_FAST_MODEL_NAME": "fast-model"}, clear=True):
            with self.assertRaisesRegex(RoutingError, "strong author route"):
                author_route_from_environment(ModelTier.STRONG)


if __name__ == "__main__":
    unittest.main()
