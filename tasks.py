from dataclasses import dataclass


@dataclass
class GatewayResult:
    approved: bool
    reference: str | None = None


class PaymentGateway:
    """Replace this stub with a real provider integration."""

    def charge(self, amount_cents: int, idempotency_key: str) -> GatewayResult:
        # A real gateway should also receive the idempotency key.
        return GatewayResult(approved=True, reference=f"mock-{idempotency_key}")