from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import Base, engine, get_db
from app.models import Order, Payment
from app.rate_limit import enforce_rate_limit
from app.tasks import process_payment

Base.metadata.create_all(bind=engine)  # Use Alembic migrations in production.

app = FastAPI(title="Distributed Order & Payment Processing API")


class OrderRequest(BaseModel):
    amount_cents: int = Field(gt=0)


class PaymentResponse(BaseModel):
    id: int
    order_id: int
    status: str
    idempotency_key: str


@app.post("/orders", status_code=201)
def create_order(payload: OrderRequest, db: Session = Depends(get_db)):
    order = Order(amount_cents=payload.amount_cents)
    db.add(order)
    db.commit()
    db.refresh(order)
    return {"id": order.id, "amount_cents": order.amount_cents, "status": order.status}


@app.post("/orders/{order_id}/payments", response_model=PaymentResponse)
def create_payment(
    order_id: int,
    request: Request,
    idempotency_key: str = Header(min_length=1, max_length=128),
    db: Session = Depends(get_db),
):
    enforce_rate_limit(request)

    with db.begin():
        # Serialize payment creation for this order.
        order = db.execute(
            select(Order).where(Order.id == order_id).with_for_update()
        ).scalar_one_or_none()
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")

        # Return the original result for a repeated idempotency key.
        existing = db.execute(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        ).scalar_one_or_none()

        if existing:
            if existing.order_id != order_id:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was already used for another order",
                )
            payment = existing
        else:
            # ON CONFLICT handles the same key arriving concurrently for another order.
            statement = (
                insert(Payment)
                .values(
                    order_id=order_id,
                    idempotency_key=idempotency_key,
                    status="queued",
                )
                .on_conflict_do_nothing(index_elements=["idempotency_key"])
                .returning(Payment.id)
            )
            payment_id = db.execute(statement).scalar_one_or_none()

            if payment_id is None:
                payment = db.execute(
                    select(Payment).where(
                        Payment.idempotency_key == idempotency_key
                    )
                ).scalar_one()
                if payment.order_id != order_id:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key was already used for another order",
                    )
            else:
                payment = db.get(Payment, payment_id)

    # Safe to enqueue more than once: the worker atomically claims queued payments.
    if payment.status == "queued":
        process_payment.delay(payment.id)

    return PaymentResponse(
        id=payment.id,
        order_id=payment.order_id,
        status=payment.status,
        idempotency_key=payment.idempotency_key,
    )