from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class TimestampMixin:
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(UserMixin, TimestampMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(24), nullable=False, default="seller", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def is_active(self):
        return self.active

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Category(TimestampMixin, db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255))
    active = db.Column(db.Boolean, nullable=False, default=True)


class Brand(TimestampMixin, db.Model):
    __tablename__ = "brands"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Supplier(TimestampMixin, db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    contact = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    nit = db.Column(db.String(40))
    address = db.Column(db.String(255))
    active = db.Column(db.Boolean, nullable=False, default=True)


class Customer(TimestampMixin, db.Model):
    __tablename__ = "customers"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    document = db.Column(db.String(40), index=True)
    phone = db.Column(db.String(40))
    email = db.Column(db.String(160))
    address = db.Column(db.String(255))
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Product(TimestampMixin, db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(64), unique=True, nullable=False, index=True)
    barcode = db.Column(db.String(64), unique=True)
    name = db.Column(db.String(180), nullable=False, index=True)
    description = db.Column(db.Text)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    brand_id = db.Column(db.Integer, db.ForeignKey("brands.id", ondelete="SET NULL"), index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"))
    model_reference = db.Column(db.String(120))
    compatibility = db.Column(db.String(255))
    cost_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    sale_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    minimum_stock = db.Column(db.Integer, nullable=False, default=0)
    location = db.Column(db.String(80))
    image_path = db.Column(db.String(255))
    active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    category = db.relationship(Category)
    brand = db.relationship(Brand)
    supplier = db.relationship(Supplier)


class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    movement_type = db.Column(db.String(32), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    before_stock = db.Column(db.Integer, nullable=False)
    after_stock = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(255), nullable=False)
    reference = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    product = db.relationship(Product)
    user = db.relationship(User)


class CashSession(db.Model):
    __tablename__ = "cash_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    opened_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    opening_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    closed_at = db.Column(db.DateTime)
    counted_amount = db.Column(db.Numeric(12, 2))
    expected_amount = db.Column(db.Numeric(12, 2))
    notes = db.Column(db.String(255))
    user = db.relationship(User)
    @property
    def is_open(self):
        return self.closed_at is None


class Sale(db.Model):
    __tablename__ = "sales"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(24), unique=True, nullable=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id", ondelete="SET NULL"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    cash_session_id = db.Column(db.Integer, db.ForeignKey("cash_sessions.id", ondelete="SET NULL"))
    subtotal = db.Column(db.Numeric(12, 2), nullable=False)
    discount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    total = db.Column(db.Numeric(12, 2), nullable=False)
    payment_method = db.Column(db.String(32), nullable=False)
    idempotency_key = db.Column(db.String(64), unique=True)
    status = db.Column(db.String(24), nullable=False, default="completed", index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    customer = db.relationship(Customer)
    user = db.relationship(User)
    lines = db.relationship("SaleLine", backref="sale", cascade="all, delete-orphan")


class SaleLine(db.Model):
    __tablename__ = "sale_lines"
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey("sales.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    product_name = db.Column(db.String(180), nullable=False)
    sku = db.Column(db.String(64), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    product = db.relationship(Product)


class Purchase(db.Model):
    __tablename__ = "purchases"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(24), unique=True, nullable=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    reference = db.Column(db.String(100))
    status = db.Column(db.String(24), nullable=False, default="pending", index=True)
    total = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    notes = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    received_at = db.Column(db.DateTime)
    supplier = db.relationship(Supplier)
    lines = db.relationship("PurchaseLine", backref="purchase", cascade="all, delete-orphan")


class PurchaseLine(db.Model):
    __tablename__ = "purchase_lines"
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False)
    line_total = db.Column(db.Numeric(12, 2), nullable=False)
    product = db.relationship(Product)


class Expense(db.Model):
    __tablename__ = "expenses"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    cash_session_id = db.Column(db.Integer, db.ForeignKey("cash_sessions.id", ondelete="SET NULL"))
    category = db.Column(db.String(80), nullable=False)
    concept = db.Column(db.String(180), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_method = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    user = db.relationship(User)
    cash_session = db.relationship(CashSession)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(80), nullable=False, index=True)
    module = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(255), nullable=False)
    reference = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    user = db.relationship(User)


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


def audit(user_id, action, module, detail, reference=None):
    db.session.add(AuditLog(user_id=user_id, action=action, module=module, detail=detail, reference=reference))
