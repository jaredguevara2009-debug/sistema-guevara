import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.models import (AuditLog, CashSession, Customer, Expense, InventoryMovement,
                        Product, Purchase, PurchaseLine, Sale, SaleLine, Supplier)
from app.operations import bp
from app.security import roles_required

MAX_MONEY = Decimal("9999999999.99")


def record(action, module, detail, reference=None):
    db.session.add(AuditLog(user_id=current_user.id, action=action, module=module, detail=detail, reference=reference))


def amount(value, label):
    try:
        result = Decimal(str(value).replace(",", "."))
        if not result.is_finite() or result < 0 or result > MAX_MONEY:
            raise InvalidOperation
        return result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} debe ser un importe válido mayor o igual a cero.")


def get_open_cash():
    return CashSession.query.filter_by(user_id=current_user.id).filter(CashSession.closed_at.is_(None)).first()


@bp.route("/inventario", methods=["GET", "POST"])
@login_required
@roles_required("admin", "warehouse")
def inventory():
    if request.method == "POST":
        try:
            product_id = request.form.get("product_id", type=int)
            product = db.session.execute(db.select(Product).where(Product.id == product_id).with_for_update()).scalar_one_or_none()
            if not product:
                raise ValueError("Selecciona un producto válido.")
            qty = int(request.form.get("quantity", "0"))
            direction = request.form.get("direction")
            reason = request.form.get("reason", "").strip()
            if qty <= 0 or direction not in {"in", "out"} or not reason:
                raise ValueError("Indica un producto, una cantidad positiva, el tipo y el motivo.")
            delta = qty if direction == "in" else -qty
            before = product.stock
            after = before + delta
            if after < 0:
                raise ValueError("El ajuste dejaría existencias negativas.")
            if after > 2_147_483_647:
                raise ValueError("La existencia resultante excede el límite permitido.")
            product.stock = after
            db.session.add(InventoryMovement(product_id=product.id, user_id=current_user.id,
                movement_type="adjustment_in" if delta > 0 else "adjustment_out", quantity=delta,
                before_stock=before, after_stock=after, reason=reason))
            record("Ajuste de inventario", "Inventario", f"{product.sku}: {before} → {after}. {reason}", f"producto:{product.id}")
            db.session.commit()
            flash("Movimiento de inventario registrado.", "success")
            return redirect(url_for("operations.inventory"))
        except (ValueError, TypeError, LookupError) as error:
            db.session.rollback()
            flash(str(error), "error")
    q = request.args.get("q", "").strip()
    query = Product.query.filter_by(active=True)
    if q:
        query = query.filter(db.or_(Product.name.ilike(f"%{q}%"), Product.sku.ilike(f"%{q}%")))
    products = query.order_by(Product.stock.asc(), Product.name.asc()).all()
    movements = InventoryMovement.query.order_by(InventoryMovement.created_at.desc()).limit(30).all()
    return render_template("operations/inventory.html", products=products, movements=movements, q=q,
                           low_count=Product.query.filter(Product.active.is_(True), Product.stock <= Product.minimum_stock).count())


@bp.route("/ventas", methods=["GET", "POST"])
@login_required
@roles_required("admin", "seller")
def pos():
    if request.method == "POST":
        try:
            cash = get_open_cash()
            if not cash:
                raise ValueError("Abre una caja antes de registrar ventas.")
            key = request.form.get("idempotency_key", "")[:64]
            existing = Sale.query.filter_by(idempotency_key=key).first() if key else None
            if existing:
                return redirect(url_for("operations.receipt", sale_id=existing.id))
            cart = json.loads(request.form.get("cart", "[]"))
            if not isinstance(cart, list) or not cart or len(cart) > 100 or any(not isinstance(row, dict) for row in cart):
                raise ValueError("Agrega al menos un producto al carrito.")
            quantities = {}
            for row in cart:
                product_id, qty = int(row.get("id", 0)), int(row.get("qty", 0))
                if qty < 1 or qty > 2_147_483_647:
                    raise ValueError("La cantidad de cada producto debe ser positiva.")
                quantities[product_id] = quantities.get(product_id, 0) + qty
            products = db.session.execute(db.select(Product).where(Product.id.in_(quantities)).with_for_update()).scalars().all()
            if len(products) != len(quantities):
                raise ValueError("Uno de los productos ya no está disponible.")
            subtotal = Decimal("0.00")
            lines = []
            for product in products:
                qty = quantities[product.id]
                if not product.active or product.stock < qty:
                    raise ValueError(f"Stock insuficiente para {product.name}.")
                line_total = (product.sale_price * qty).quantize(Decimal("0.01"))
                subtotal += line_total
                if subtotal > MAX_MONEY:
                    raise ValueError("El total de la venta supera el máximo permitido.")
                lines.append((product, qty, line_total))
            discount = amount(request.form.get("discount", "0"), "El descuento")
            max_discount = subtotal * (Decimal("0.20") if current_user.role == "admin" else Decimal("0.05"))
            if discount > max_discount or discount > subtotal:
                raise ValueError("El descuento supera el límite permitido para tu rol.")
            payment = request.form.get("payment_method", "")
            if payment not in {"Efectivo", "Transferencia", "QR", "Tarjeta", "Otro"}:
                raise ValueError("Selecciona un método de pago válido.")
            customer_id = request.form.get("customer_id", type=int)
            customer = db.session.get(Customer, customer_id) if customer_id else Customer.query.filter_by(is_default=True, active=True).first()
            if not customer or not customer.active:
                raise ValueError("Selecciona un cliente válido.")
            sale = Sale(number=None, customer=customer, user_id=current_user.id,
                        cash_session_id=cash.id, subtotal=subtotal, discount=discount,
                        total=(subtotal - discount).quantize(Decimal("0.01")),
                        payment_method=payment, status="completed", idempotency_key=key or None)
            db.session.add(sale)
            db.session.flush()
            sale.number = f"V-{datetime.utcnow():%y%m%d}-{sale.id:06d}"
            for product, qty, line_total in lines:
                before = product.stock
                product.stock -= qty
                db.session.add(SaleLine(sale_id=sale.id, product_id=product.id, product_name=product.name,
                    sku=product.sku, quantity=qty, unit_price=product.sale_price,
                    unit_cost=product.cost_price, line_total=line_total))
                db.session.add(InventoryMovement(product_id=product.id, user_id=current_user.id,
                    movement_type="sale", quantity=-qty, before_stock=before, after_stock=product.stock,
                    reason=f"Venta {sale.number}", reference=sale.number))
            record("Venta registrada", "Ventas", f"Venta {sale.number} por {sale.total}", sale.number)
            db.session.commit()
            return redirect(url_for("operations.receipt", sale_id=sale.id))
        except (ValueError, TypeError, InvalidOperation, json.JSONDecodeError, LookupError) as error:
            db.session.rollback()
            flash(str(error), "error")
    products = Product.query.filter(Product.active.is_(True), Product.stock > 0).order_by(Product.name).all()
    customers = Customer.query.filter_by(active=True).order_by(Customer.is_default.desc(), Customer.name).all()
    sales = Sale.query.order_by(Sale.created_at.desc()).limit(12).all()
    return render_template("operations/pos.html", products=products, customers=customers,
                           sales=sales, cash_open=bool(get_open_cash()))


@bp.get("/ventas/<int:sale_id>/comprobante")
@login_required
def receipt(sale_id):
    sale = db.get_or_404(Sale, sale_id)
    return render_template("operations/receipt.html", sale=sale)


@bp.get("/compras")
@login_required
@roles_required("admin", "warehouse")
def purchases():
    rows = Purchase.query.order_by(Purchase.created_at.desc()).limit(100).all()
    return render_template("operations/purchases.html", rows=rows)


@bp.route("/compras/nueva", methods=["GET", "POST"])
@login_required
@roles_required("admin", "warehouse")
def purchase_new():
    if request.method == "POST":
        try:
            supplier = db.session.get(Supplier, request.form.get("supplier_id", type=int))
            cart = json.loads(request.form.get("cart", "[]"))
            if not supplier or not supplier.active or not isinstance(cart, list) or not cart or len(cart) > 100 or any(not isinstance(row, dict) for row in cart):
                raise ValueError("Selecciona un proveedor activo y agrega productos.")
            purchase = Purchase(number=None, supplier=supplier, user_id=current_user.id,
                                reference=request.form.get("reference", "").strip(), status="pending")
            db.session.add(purchase)
            db.session.flush()
            purchase.number = f"C-{datetime.utcnow():%y%m%d}-{purchase.id:06d}"
            total = Decimal("0.00")
            for row in cart:
                product = db.session.get(Product, int(row.get("id", 0)))
                qty = int(row.get("qty", 0))
                cost = amount(row.get("cost", 0), "El costo")
                if not product or not product.active or qty <= 0 or qty > 2_147_483_647:
                    raise ValueError("Revisa los productos y cantidades de la compra.")
                line_total = (cost * qty).quantize(Decimal("0.01"))
                total += line_total
                if total > MAX_MONEY:
                    raise ValueError("El total de la compra supera el máximo permitido.")
                db.session.add(PurchaseLine(purchase_id=purchase.id, product_id=product.id,
                    quantity=qty, unit_cost=cost, line_total=line_total))
            purchase.total = total
            record("Compra registrada", "Compras", f"Compra pendiente {purchase.number} por {total}", purchase.number)
            db.session.commit()
            flash("Compra guardada como pendiente. Recíbela cuando llegue la mercadería.", "success")
            return redirect(url_for("operations.purchases"))
        except (ValueError, TypeError, InvalidOperation, json.JSONDecodeError, LookupError) as error:
            db.session.rollback()
            flash(str(error), "error")
    return render_template("operations/purchase_form.html",
        suppliers=Supplier.query.filter_by(active=True).order_by(Supplier.name).all(),
        products=Product.query.filter_by(active=True).order_by(Product.name).all())


@bp.post("/compras/<int:purchase_id>/recibir")
@login_required
@roles_required("admin", "warehouse")
def purchase_receive(purchase_id):
    try:
        purchase = db.session.execute(db.select(Purchase).where(Purchase.id == purchase_id).with_for_update()).scalar_one_or_none()
        if not purchase:
            raise ValueError("No encontramos esa compra.")
        if purchase.status != "pending":
            raise ValueError("Esta compra ya fue recibida o cancelada.")
        for line in purchase.lines:
            product = db.session.execute(db.select(Product).where(Product.id == line.product_id).with_for_update()).scalar_one_or_none()
            if not product:
                raise ValueError("Uno de los productos de la compra ya no está disponible.")
            before = product.stock
            new_stock = before + line.quantity
            if new_stock > 2_147_483_647:
                raise ValueError("La recepción excede la capacidad del inventario para este producto.")
            if new_stock > 0:
                product.cost_price = ((product.cost_price * before + line.unit_cost * line.quantity) / new_stock).quantize(Decimal("0.01"))
            product.stock = new_stock
            db.session.add(InventoryMovement(product_id=product.id, user_id=current_user.id,
                movement_type="purchase", quantity=line.quantity, before_stock=before,
                after_stock=new_stock, reason=f"Recepción de compra {purchase.number}", reference=purchase.number))
        purchase.status = "received"
        purchase.received_at = datetime.utcnow()
        record("Compra recibida", "Compras", f"Compra {purchase.number}; inventario actualizado", purchase.number)
        db.session.commit()
        flash("Compra recibida. Se actualizaron existencias y costo promedio ponderado.", "success")
    except (ValueError, LookupError) as error:
        db.session.rollback()
        flash(str(error), "error")
    return redirect(url_for("operations.purchases"))


@bp.route("/caja", methods=["GET", "POST"])
@login_required
def cash():
    if request.method == "POST":
        if get_open_cash():
            flash("Ya tienes una caja abierta.", "error")
        else:
            try:
                opening = amount(request.form.get("opening_amount", "0"), "El monto inicial")
                session = CashSession(user_id=current_user.id, opening_amount=opening,
                                      notes=request.form.get("notes", "").strip())
                db.session.add(session)
                db.session.flush()
                record("Caja abierta", "Caja", f"Apertura con Bs {opening}", f"caja:{session.id}")
                db.session.commit()
                flash("Caja abierta.", "success")
            except ValueError as error:
                db.session.rollback()
                flash(str(error), "error")
        return redirect(url_for("operations.cash"))
    active = get_open_cash()
    rows = CashSession.query.order_by(CashSession.opened_at.desc()).limit(30).all()
    return render_template("operations/cash.html", active=active, rows=rows,
                           expected=expected_cash(active) if active else None)


def expected_cash(session):
    cash_sales = db.session.query(func.coalesce(func.sum(Sale.total), 0)).filter(
        Sale.cash_session_id == session.id, Sale.payment_method == "Efectivo", Sale.status == "completed").scalar()
    cash_expenses = db.session.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
        Expense.cash_session_id == session.id, Expense.payment_method == "Efectivo").scalar()
    return (session.opening_amount + Decimal(str(cash_sales or 0)) - Decimal(str(cash_expenses or 0))).quantize(Decimal("0.01"))


@bp.post("/caja/<int:session_id>/cerrar")
@login_required
def cash_close(session_id):
    session = db.get_or_404(CashSession, session_id)
    if session.user_id != current_user.id and current_user.role != "admin":
        abort(403)
    if not session.is_open:
        flash("Esta caja ya fue cerrada.", "error")
        return redirect(url_for("operations.cash"))
    try:
        counted = amount(request.form.get("counted_amount", ""), "El efectivo contado")
        session.expected_amount = expected_cash(session)
        session.counted_amount = counted
        session.closed_at = datetime.utcnow()
        record("Caja cerrada", "Caja", f"Caja {session.id}; diferencia Bs {counted - session.expected_amount}", f"caja:{session.id}")
        db.session.commit()
        flash("Caja cerrada y resumen guardado.", "success")
    except ValueError as error:
        db.session.rollback()
        flash(str(error), "error")
    return redirect(url_for("operations.cash"))


@bp.route("/gastos", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def expenses():
    if request.method == "POST":
        try:
            category = request.form.get("category", "").strip()
            concept = request.form.get("concept", "").strip()
            method = request.form.get("payment_method", "")
            value = amount(request.form.get("amount", ""), "El importe")
            if not category or not concept or value <= 0 or method not in {"Efectivo", "Transferencia", "QR", "Tarjeta", "Otro"}:
                raise ValueError("Completa todos los campos del gasto.")
            cash = get_open_cash() if method == "Efectivo" else None
            if method == "Efectivo" and not cash:
                raise ValueError("Abre caja antes de registrar un gasto en efectivo.")
            expense = Expense(user_id=current_user.id, cash_session=cash, category=category,
                              concept=concept, amount=value, payment_method=method)
            db.session.add(expense)
            record("Gasto registrado", "Gastos", f"{concept}: Bs {value}")
            db.session.commit()
            flash("Gasto registrado.", "success")
            return redirect(url_for("operations.expenses"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "error")
    rows = Expense.query.order_by(Expense.created_at.desc()).limit(100).all()
    return render_template("operations/expenses.html", rows=rows)


@bp.get("/auditoria")
@login_required
@roles_required("admin")
def audit_log():
    rows = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template("operations/audit.html", rows=rows)
