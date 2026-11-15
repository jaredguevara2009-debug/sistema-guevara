from datetime import datetime, timedelta
import csv
import io
from decimal import Decimal

from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from app.extensions import db
from app.models import AuditLog, Category, Customer, Expense, Product, Purchase, Sale, Setting, Supplier, User
from app.security import roles_required
from app.time_utils import local_date_start, local_day_bounds, local_now
from app.validation import normalize_email

bp = Blueprint("views", __name__)


@bp.get("/")
def index():
    from flask_login import current_user
    from flask import redirect, url_for

    return redirect(url_for("views.dashboard" if current_user.is_authenticated else "auth.login"))


@bp.get("/dashboard")
@login_required
def dashboard():
    today = local_now(current_app.config["TIMEZONE"]).date()
    start, tomorrow = local_day_bounds(today, current_app.config["TIMEZONE"])
    month_start = local_date_start(today.replace(day=1), current_app.config["TIMEZONE"])
    sales_today = Sale.query.filter(Sale.created_at >= start, Sale.created_at < tomorrow, Sale.status == "completed").all()
    sales_month = Sale.query.filter(Sale.created_at >= month_start, Sale.status == "completed").all()
    low_stock = Product.query.filter(Product.active.is_(True), Product.stock <= Product.minimum_stock).order_by(Product.stock.asc()).limit(8).all()
    trend_labels, trend_values = [], []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        day_start, day_end = local_day_bounds(day, current_app.config["TIMEZONE"])
        value = db.session.query(func.coalesce(func.sum(Sale.total), 0)).filter(
            Sale.created_at >= day_start, Sale.created_at < day_end, Sale.status == "completed"
        ).scalar()
        trend_labels.append(day.strftime("%d/%m"))
        trend_values.append(float(value or 0))
    metrics = {
        "products": Product.query.filter_by(active=True).count(),
        "available": Product.query.filter(Product.active.is_(True), Product.stock > 0).count(),
        "low": Product.query.filter(Product.active.is_(True), Product.stock <= Product.minimum_stock, Product.stock > 0).count(),
        "out": Product.query.filter(Product.active.is_(True), Product.stock <= 0).count(),
        "sales_today": len(sales_today),
        "income_today": sum((sale.total for sale in sales_today), Decimal("0.00")),
        "sales_month": len(sales_month),
        "income_month": sum((sale.total for sale in sales_month), Decimal("0.00")),
        "customers": Customer.query.filter_by(active=True).count(),
        "suppliers": Supplier.query.filter_by(active=True).count(),
    }
    recent_sales = Sale.query.order_by(Sale.created_at.desc()).limit(6).all()
    activity = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(6).all()
    pending_purchases = Purchase.query.filter_by(status="pending").count()
    return render_template("dashboard.html", metrics=metrics, low_stock=low_stock,
                           recent_sales=recent_sales, activity=activity,
                           trend_labels=trend_labels, trend_values=trend_values,
                           pending_purchases=pending_purchases)


@bp.get("/reportes")
@login_required
def reports():
    products = Product.query.filter_by(active=True).all()
    query = Sale.query.filter_by(status="completed")
    start, end = request.args.get("desde", ""), request.args.get("hasta", "")
    if start:
        try:
            date_value = datetime.strptime(start, "%Y-%m-%d").date()
            query = query.filter(Sale.created_at >= local_date_start(date_value, current_app.config["TIMEZONE"]))
        except ValueError:
            flash("La fecha inicial no es válida.", "error")
    if end:
        try:
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
            query = query.filter(Sale.created_at < local_day_bounds(end_date, current_app.config["TIMEZONE"])[1])
        except ValueError:
            flash("La fecha final no es válida.", "error")
    sales = query.order_by(Sale.created_at.desc()).limit(500).all()
    total_stock_cost = sum((p.cost_price * p.stock for p in products), Decimal("0.00"))
    revenue = sum((sale.total for sale in sales), Decimal("0.00"))
    cogs = sum((line.unit_cost * line.quantity for sale in sales for line in sale.lines), Decimal("0.00"))
    return render_template("reports.html", products=products, sales=sales, total_stock_cost=total_stock_cost,
                           revenue=revenue, cogs=cogs, gross_profit=revenue-cogs, start=start, end=end)


@bp.get("/reportes/ventas.csv")
@login_required
@roles_required("admin", "seller", "warehouse", "viewer")
def reports_csv():
    rows = Sale.query.filter_by(status="completed").order_by(Sale.created_at.desc()).limit(5000).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Venta", "Fecha UTC", "Cliente", "Vendedor", "Productos", "Pago", "Subtotal Bs", "Descuento Bs", "Total Bs"])
    def safe_cell(value):
        if isinstance(value, str) and value[:1] in {"=", "+", "-", "@", "\t", "\r"}:
            return "'" + value
        return value
    for sale in rows:
        writer.writerow([safe_cell(sale.number), sale.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            safe_cell(sale.customer.name if sale.customer else "Consumidor final"), safe_cell(sale.user.name if sale.user else ""),
            sum(line.quantity for line in sale.lines), safe_cell(sale.payment_method), sale.subtotal, sale.discount, sale.total])
    return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=ventas-repuestos-guevara.csv"})


@bp.route("/administracion/usuarios", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def users():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        try:
            email = (normalize_email(request.form.get("email", "")) or "").lower()
        except ValueError as error:
            email = ""
            flash(str(error), "error")
        password = request.form.get("password", "")
        role = request.form.get("role", "seller")
        if role not in {"admin", "seller", "warehouse", "viewer"} or not name or len(name) > 120 or not email or len(email) > 160 or len(password) < 12:
            flash("Completa los datos. La contraseña debe tener 12 caracteres como mínimo.", "error")
        elif User.query.filter_by(email=email).first():
            flash("Ya existe una cuenta con ese correo.", "error")
        else:
            user = User(name=name, email=email, role=role, active=True)
            user.set_password(password)
            db.session.add(user)
            db.session.add(AuditLog(user_id=current_user.id, action="Usuario creado", module="Usuarios", detail=f"{email} ({role})"))
            db.session.commit()
            flash("Usuario creado.", "success")
            return redirect(url_for("views.users"))
    rows = User.query.order_by(User.name).all()
    return render_template("users.html", rows=rows)


@bp.post("/administracion/usuarios/<int:user_id>/estado")
@login_required
@roles_required("admin")
def user_toggle(user_id):
    user = db.get_or_404(User, user_id)
    if user.id == current_user.id:
        flash("No puedes desactivar tu propia cuenta.", "error")
    elif user.role == "admin" and user.active and User.query.filter_by(role="admin", active=True).count() <= 1:
        flash("Debe permanecer al menos una cuenta administradora activa.", "error")
    else:
        user.active = not user.active
        db.session.add(AuditLog(user_id=current_user.id, action="Estado de usuario", module="Usuarios", detail=f"{user.email}: {'activo' if user.active else 'inactivo'}"))
        db.session.commit()
        flash("Estado actualizado.", "success")
    return redirect(url_for("views.users"))


@bp.route("/configuracion", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def settings():
    keys = {"business_name": "Nombre comercial", "business_phone": "Teléfono", "business_address": "Dirección", "receipt_message": "Mensaje de comprobante"}
    if request.method == "POST":
        for key in keys:
            value = request.form.get(key, "").strip()
            item = db.session.get(Setting, key)
            if item:
                item.value = value
            else:
                db.session.add(Setting(key=key, value=value))
        db.session.add(AuditLog(user_id=current_user.id, action="Configuración actualizada", module="Configuración", detail="Datos del negocio y comprobantes"))
        db.session.commit()
        flash("Configuración guardada.", "success")
        return redirect(url_for("views.settings"))
    values = {}
    for key in keys:
        item = db.session.get(Setting, key)
        values[key] = item.value if item else ""
    return render_template("settings.html", keys=keys, values=values)
