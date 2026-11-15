import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app import create_app
from app.extensions import db
from app.models import CashSession, Customer, Product, Purchase, Sale, Supplier, User
from config import Config


class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "test-only-key-not-for-use"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        TestConfig.UPLOAD_FOLDER = Path(self.tempdir.name) / "uploads"
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            self.admin = User(name="Admin", email="admin@example.test", role="admin", active=True)
            self.admin.set_password("a-long-test-password")
            self.customer = Customer(name="Consumidor final", is_default=True, active=True)
            self.product = Product(sku="FRE-01", name="Pastillas de freno", cost_price=Decimal("20.00"),
                                   sale_price=Decimal("35.00"), stock=4, minimum_stock=1, active=True)
            self.supplier = Supplier(name="Proveedor Uno", active=True)
            db.session.add_all([self.admin, self.customer, self.product, self.supplier])
            db.session.commit()
            self.admin_id, self.customer_id = self.admin.id, self.customer.id
            self.product_id, self.supplier_id = self.product.id, self.supplier.id
            db.session.add(CashSession(user_id=self.admin_id, opening_amount=Decimal("100.00")))
            db.session.commit()
        response = self.client.post("/login", data={"email": "admin@example.test", "password": "a-long-test-password"})
        self.assertEqual(response.status_code, 302)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.tempdir.cleanup()

    def test_sale_reduces_stock_once_and_is_idempotent(self):
        payload = {"cart": json.dumps([{"id": self.product_id, "qty": 2}]), "discount": "0",
                   "payment_method": "Efectivo", "customer_id": str(self.customer_id), "idempotency_key": "sale-test-once"}
        first = self.client.post("/operaciones/ventas", data=payload)
        self.assertEqual(first.status_code, 302)
        second = self.client.post("/operaciones/ventas", data=payload)
        self.assertEqual(second.status_code, 302)
        with self.app.app_context():
            self.assertEqual(Product.query.get(self.product_id).stock, 2)
            self.assertEqual(Sale.query.count(), 1)
            self.assertEqual(Sale.query.first().total, Decimal("70.00"))

    def test_pending_purchase_does_not_change_stock_until_received(self):
        payload = {"supplier_id": str(self.supplier_id), "reference": "FC-22",
                   "cart": json.dumps([{"id": self.product_id, "qty": 3, "cost": "24.00"}])}
        response = self.client.post("/operaciones/compras/nueva", data=payload)
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            purchase = Purchase.query.one()
            purchase_id = purchase.id
            self.assertEqual(Product.query.get(self.product_id).stock, 4)
        self.client.post(f"/operaciones/compras/{purchase_id}/recibir")
        self.client.post(f"/operaciones/compras/{purchase_id}/recibir")
        with self.app.app_context():
            self.assertEqual(Product.query.get(self.product_id).stock, 7)
            self.assertEqual(Purchase.query.get(purchase_id).status, "received")
            self.assertEqual(Product.query.get(self.product_id).cost_price, Decimal("21.71"))

    def test_unauthenticated_user_cannot_open_dashboard(self):
        self.client.post("/logout")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
