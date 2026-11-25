import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from dotenv import load_dotenv
from flask import Flask, url_for
from sqlalchemy import insert, select

load_dotenv()

from config import Config
from app.extensions import csrf, db, login_manager, migrate
from app.time_utils import local_now
from app.validation import normalize_email


def create_app(config_object=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.urandom(32)
        app.logger.warning("SECRET_KEY no configurada; las sesiones no persistirán al reiniciar.")
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app import models  # noqa: F401
    from app.auth import bp as auth_bp
    from app.catalog import bp as catalog_bp
    from app.operations import bp as operations_bp
    from app.views import bp as views_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(catalog_bp, url_prefix="/catalogo")
    app.register_blueprint(operations_bp, url_prefix="/operaciones")

    optional_tables_ready = False

    @app.before_request
    def ensure_optional_tables():
        """Create additive tables and link legacy product brand/category pairs."""
        nonlocal optional_tables_ready
        if optional_tables_ready:
            return
        from app.models import CustomerProfile, Product, ProductImage, SupplierProfile, brand_categories

        CustomerProfile.__table__.create(bind=db.engine, checkfirst=True)
        SupplierProfile.__table__.create(bind=db.engine, checkfirst=True)
        ProductImage.__table__.create(bind=db.engine, checkfirst=True)
        brand_categories.create(bind=db.engine, checkfirst=True)

        legacy_pairs = db.session.execute(
            select(Product.brand_id, Product.category_id)
            .where(Product.brand_id.is_not(None), Product.category_id.is_not(None))
            .distinct()
        ).all()
        if legacy_pairs:
            rows = [{"brand_id": brand_id, "category_id": category_id}
                    for brand_id, category_id in legacy_pairs]
            dialect = db.engine.dialect.name
            if dialect == "mysql":
                from sqlalchemy.dialects.mysql import insert as mysql_insert
                statement = mysql_insert(brand_categories).values(rows).prefix_with("IGNORE")
            elif dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                statement = sqlite_insert(brand_categories).values(rows).on_conflict_do_nothing()
            elif dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                statement = pg_insert(brand_categories).values(rows).on_conflict_do_nothing()
            else:
                present = set(db.session.execute(select(
                    brand_categories.c.brand_id, brand_categories.c.category_id
                )).all())
                rows = [row for row in rows if (row["brand_id"], row["category_id"]) not in present]
                statement = insert(brand_categories).values(rows) if rows else None
            if statement is not None:
                db.session.execute(statement)
                db.session.commit()
        optional_tables_ready = True

    @app.template_global()
    def product_image_url(product):
        if not product or not product.image_path:
            return ""
        if product.image_path == "database" or product.image_path.startswith("uploads/products/"):
            return url_for("catalog.product_image", product_id=product.id)
        return url_for("static", filename=product.image_path)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
            "script-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'")
        return response

    @app.template_filter("money")
    def money(value):
        amount = Decimal(str(value or 0))
        return f"Bs {amount:,.2f}"

    @app.template_filter("local_dt")
    def local_dt(value, fmt="%d/%m/%Y %H:%M"):
        if not value:
            return "—"
        return value.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(app.config["TIMEZONE"])).strftime(fmt)

    @app.context_processor
    def shared_context():
        business = {}
        try:
            from app.models import Setting
            business = {item.key: item.value for item in Setting.query.filter(Setting.key.in_(
                ["business_name", "business_phone", "business_address", "receipt_message"])).all()}
        except Exception:
            db.session.rollback()
        return {
            "business_name": business.get("business_name") or app.config["BUSINESS_NAME"],
            "business_phone": business.get("business_phone") or app.config["BUSINESS_PHONE"],
            "business_address": business.get("business_address") or app.config["BUSINESS_ADDRESS"],
            "receipt_message": business.get("receipt_message") or "Gracias por tu compra.",
            "logo_available": (Path(app.static_folder) / "img" / "logo.png").exists(),
            "now": local_now(app.config["TIMEZONE"]),
        }

    @app.cli.command("create-admin")
    def create_admin():
        """Crea la primera cuenta de administración solicitando credenciales."""
        from app.models import User

        if User.query.filter_by(role="admin").first():
            click.echo("Ya existe una cuenta administradora. No se creó otra.")
            return
        name = click.prompt("Nombre completo")
        try:
            email = (normalize_email(click.prompt("Correo de acceso")) or "").lower()
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        password = click.prompt("Contraseña", hide_input=True, confirmation_prompt=True)
        if len(password) < 12:
            raise click.ClickException("La contraseña debe tener al menos 12 caracteres.")
        if not email:
            raise click.ClickException("El correo de acceso es obligatorio.")
        if User.query.filter_by(email=email).first():
            raise click.ClickException("Ese correo ya está registrado.")
        user = User(name=name, email=email, role="admin", active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Cuenta administradora creada para {email}.")

    @app.cli.command("seed-reference")
    def seed_reference():
        """Crea el cliente de consumidor final y categorías iniciales."""
        from app.models import Category, Customer

        if not Customer.query.filter_by(name="Consumidor final").first():
            db.session.add(Customer(name="Consumidor final", is_default=True, active=True))
        names = ["Frenos", "Motor", "Transmisión", "Suspensión", "Sistema eléctrico", "Iluminación", "Accesorios", "Otros"]
        for name in names:
            if not Category.query.filter_by(name=name).first():
                db.session.add(Category(name=name, active=True))
        db.session.commit()
        click.echo("Datos base listos.")

    @app.errorhandler(403)
    def forbidden(_error):
        from flask import render_template

        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        from flask import render_template

        return render_template("errors/404.html"), 404

    return app


@login_manager.user_loader
def load_user(user_id):
    from app.models import User

    user = db.session.get(User, int(user_id))
    return user if user and user.active else None
