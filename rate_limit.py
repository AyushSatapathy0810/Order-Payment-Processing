from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_order_amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    payments: Mapped[list["Payment"]] = relationship(back_populates="order")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed')",
            name="ck_payment_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    gateway_reference: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    order: Mapped[Order] = relationship(back_populates="payments")