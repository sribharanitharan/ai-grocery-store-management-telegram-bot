from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime, ForeignKey, Text
)
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    sku = Column(String, unique=True)
    unit = Column(String, default="piece")  # kg/g/litre/ml/packet/piece/dozen
    is_loose = Column(Boolean, default=False)
    cost_price = Column(Float, default=0.0)
    mrp = Column(Float, default=0.0)
    quantity = Column(Float, default=0.0)
    reorder_lvl = Column(Float, default=5.0)
    hsn_code = Column(String, default="")
    gst_slab = Column(Float, default=0.0)  # 0, 5, 12, 18
    created_at = Column(DateTime, default=datetime.utcnow)

    stock_logs = relationship("StockLog", back_populates="product")
    bill_items = relationship("BillItem", back_populates="product")


class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, nullable=False)
    status = Column(String, default="draft")  # draft | finalized | cancelled
    customer = Column(String, default="")
    payment_mode = Column(String, default="cash")  # cash | upi | card
    payment_ref = Column(String, default="")
    subtotal = Column(Float, default=0.0)
    cgst = Column(Float, default=0.0)
    sgst = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    idempotency_key = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    finalized_at = Column(DateTime, nullable=True)

    items = relationship("BillItem", back_populates="bill", cascade="all, delete-orphan")


class BillItem(Base):
    __tablename__ = "bill_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    qty = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    gst_slab = Column(Float, default=0.0)
    line_total = Column(Float, nullable=False)

    bill = relationship("Bill", back_populates="items")
    product = relationship("Product", back_populates="bill_items")


class Khata(Base):
    """Credit ledger. Positive delta = credit given, negative = payment received."""
    __tablename__ = "khata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer = Column(String, nullable=False)
    delta = Column(Float, nullable=False)
    note = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class OwnerPreference(Base):
    __tablename__ = "owner_preferences"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)


class StockLog(Base):
    """Audit trail for every stock movement."""
    __tablename__ = "stock_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    delta = Column(Float, nullable=False)
    reason = Column(String, default="adjustment")  # received | sold | adjustment
    bill_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="stock_logs")
