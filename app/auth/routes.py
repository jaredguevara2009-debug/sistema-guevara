from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.auth import bp
from app.extensions import db
from app.models import AuditLog, User

ATTEMPTS = {}


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("views.dashboard"))
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        now = datetime.utcnow()
        window = ATTEMPTS.get(ip)
        if window and window[0] > now and window[1] >= 8:
            flash("Demasiados intentos. Espera 10 minutos antes de volver a intentar.", "error")
            return render_template("auth/login.html"), 429
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.active and user.check_password(password):
            ATTEMPTS.pop(ip, None)
            login_user(user, remember=False, fresh=True)
            db.session.add(AuditLog(user_id=user.id, action="Inicio de sesión", module="Acceso", detail="Acceso correcto"))
            db.session.commit()
            destination = request.args.get("next", "")
            if not destination.startswith("/") or destination.startswith("//") or "\\" in destination:
                destination = url_for("views.dashboard")
            return redirect(destination)
        if not window or window[0] <= now:
            ATTEMPTS[ip] = (now + timedelta(minutes=10), 1)
        else:
            ATTEMPTS[ip] = (window[0], window[1] + 1)
        flash("Correo o contraseña incorrectos, o cuenta desactivada.", "error")
    return render_template("auth/login.html")


@bp.post("/logout")
@login_required
def logout():
    db.session.add(AuditLog(user_id=current_user.id, action="Cierre de sesión", module="Acceso", detail="Sesión cerrada"))
    db.session.commit()
    logout_user()
    flash("Sesión cerrada.", "success")
    return redirect(url_for("auth.login"))
