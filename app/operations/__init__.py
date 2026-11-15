from flask import Blueprint

bp = Blueprint("operations", __name__)

from app.operations import routes  # noqa: E402,F401
