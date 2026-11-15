import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from dotenv import load_dotenv
from flask import Flask

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
