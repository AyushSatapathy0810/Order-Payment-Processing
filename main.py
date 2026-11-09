import os

from celery import Celery
from sqlalchemy import select, update

from app.db import SessionLocal
from app.gateway import PaymentGateway
from app.models import Order, Payment

celery_app = Celery(
    "payments",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)


@celery_app.task(name="process_payment")
def process_payment(payment_id: int) -> None:
    # Claim the queued payment atomically. Duplicate task deliveries become no-ops.
    with SessionLocal.begin() as db:
        claimed = db.execute(
            update(Payment)
            .where(Payment.id == payment_id, Payment.status == "queued")
            .values(status="processing", version=Payment.version + 1)
            .returning(Payment.id, Payment.order_id, Payment.idempotency_key)
        ).one_or_none()

        if claimed is None:
            return

        _, order_id, idempotency_key = claimed
        order = db.execute(
            select(Order).where(Order.id == order_id)
        ).scalar_one()
        amount_cents = order.amount_cents

    # Do not hold database locks while making a network request.
    result = PaymentGateway().charge(amount_cents, idempotency_key)

    with SessionLocal.begin() as db:
        payment = db.execute(
            select(Payment).where(Payment.id == payment_id).with_for_update()
        ).scalar_one()

        # Guard against overwriting a terminal result.
        if payment.status != "processing":
            return

        payment.status = "succeeded" if result.approved else "failed"
        payment.gateway_reference = result.reference
        payment.version += 1