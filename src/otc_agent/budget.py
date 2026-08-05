from __future__ import annotations

from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    max_model_calls: int = 12
    max_input_tokens: int = 120_000
    max_output_tokens: int = 24_000
    max_cost_usd: float = 8.0
    max_wall_seconds: float = 900.0
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def charge(self, *, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        projected = (
            self.model_calls + 1,
            self.input_tokens + input_tokens,
            self.output_tokens + output_tokens,
            self.cost_usd + cost_usd,
        )
        if projected[0] > self.max_model_calls:
            raise BudgetExceeded("model-call budget exceeded")
        if projected[1] > self.max_input_tokens or projected[2] > self.max_output_tokens:
            raise BudgetExceeded("token budget exceeded")
        if projected[3] > self.max_cost_usd:
            raise BudgetExceeded("cost budget exceeded")
        self.model_calls, self.input_tokens, self.output_tokens, self.cost_usd = projected

    def snapshot(self) -> dict[str, int | float]:
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "max_model_calls": self.max_model_calls,
            "max_cost_usd": self.max_cost_usd,
        }

