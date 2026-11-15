from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from PIL import Image, UnidentifiedImageError
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from app.catalog import bp
from app.extensions import db
from app.models import AuditLog, Brand, Category, Customer, InventoryMovement, Product, Supplier
from app.security import roles_required
from app.validation import normalize_email

MAX_MONEY = Decimal("9999999999.99")
Image.MAX_IMAGE_PIXELS = 20_000_000


def audit(action, detail, reference=None):
    db.session.add(AuditLog(user_id=current_user.id, action=action, module="Catálogo", detail=detail, reference=reference))


def parse_decimal(value, label):
    try:
        amount = Decimal((value or "").replace(",", "."))
        if not amount.is_finite() or amount < 0 or amount > MAX_MONEY:
            raise InvalidOperation
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} debe ser un importe válido mayor o igual a cero.")


def save_product_image(file):
    if not file or not file.filename:
        return None
    safe_name = secure_filename(file.filename)
    if Path(safe_name).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ValueError("Usa una imagen JPG, PNG o WebP de hasta 8 MB.")
    try:
        image = Image.open(file.stream)
        image.verify()
        file.stream.seek(0)
        image = Image.open(file.stream)
        image.thumbnail((1600, 1600))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        name = f"{uuid4().hex}.webp"
        target = Path(current_app.config["UPLOAD_FOLDER"]) / name
        image.save(target, "WEBP", quality=88, method=6)
        return f"uploads/products/{name}"
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("El archivo no contiene una imagen válida.")


@bp.get("/productos")
@login_required
def products():
    q = request.args.get("q", "").strip()
    query = Product.query
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like), Product.model_reference.ilike(like)))
    page = query.order_by(Product.name.asc()).paginate(page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    return render_template("catalog/products.html", page=page, q=q)


@bp.route("/productos/nuevo", methods=["GET", "POST"])
@bp.route("/productos/<int:product_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("admin", "warehouse")
def product_form(product_id=None):
    product = db.get_or_404(Product, product_id) if product_id else Product(active=True)
    if request.method == "POST":
        try:
            sku = request.form.get("sku", "").strip()
            name = request.form.get("name", "").strip()
            if not sku or not name:
                raise ValueError("El SKU y el nombre son obligatorios.")
            if len(sku) > 64 or len(name) > 180:
                raise ValueError("El SKU o el nombre superan el máximo de caracteres permitido.")
            duplicate = Product.query.filter(Product.sku == sku, Product.id != product.id).first()
            if duplicate:
                raise ValueError("Ya existe un producto con ese SKU.")
            barcode = request.form.get("barcode", "").strip() or None
            if barcode and Product.query.filter(Product.barcode == barcode, Product.id != product.id).first():
                raise ValueError("Ya existe un producto con ese código de barras.")
            stock = int(request.form.get("stock", "0"))
            minimum = int(request.form.get("minimum_stock", "0"))
            if stock < 0 or minimum < 0:
                raise ValueError("Las existencias y el stock mínimo no pueden ser negativos.")
            product.sku = sku
            product.barcode = barcode
            if barcode and len(barcode) > 64:
                raise ValueError("El código de barras supera el máximo de caracteres permitido.")
            product.name = name
            product.description = request.form.get("description", "").strip()
            product.category_id = request.form.get("category_id", type=int) or None
            product.brand_id = request.form.get("brand_id", type=int) or None
            product.supplier_id = request.form.get("supplier_id", type=int) or None
            product.model_reference = request.form.get("model_reference", "").strip()
            product.compatibility = request.form.get("compatibility", "").strip()
            product.cost_price = parse_decimal(request.form.get("cost_price"), "El costo")
            product.sale_price = parse_decimal(request.form.get("sale_price"), "El precio de venta")
            product.minimum_stock = minimum
            product.location = request.form.get("location", "").strip()
            if product.category_id:
                category = db.session.get(Category, product.category_id)
                if not category or not category.active:
                    raise ValueError("Selecciona una categoría activa.")
            if product.brand_id:
                brand = db.session.get(Brand, product.brand_id)
                if not brand or not brand.active:
                    raise ValueError("Selecciona una marca activa.")
            if product.supplier_id:
                supplier = db.session.get(Supplier, product.supplier_id)
                if not supplier or not supplier.active:
                    raise ValueError("Selecciona un proveedor activo.")
            is_new = product.id is None
            if is_new:
                product.stock = stock
            elif stock != product.stock:
                raise ValueError("Para modificar existencias usa el módulo Inventario, que deja el movimiento registrado.")
            uploaded = save_product_image(request.files.get("image"))
            if uploaded:
                product.image_path = uploaded
            db.session.add(product)
            db.session.flush()
            if is_new and stock:
                db.session.add(InventoryMovement(product_id=product.id, user_id=current_user.id,
                    movement_type="initial", quantity=stock, before_stock=0, after_stock=stock,
                    reason="Existencia inicial al registrar producto"))
            audit("Producto guardado", f"Producto {product.name} ({product.sku})", f"producto:{product.id}")
            db.session.commit()
            flash("Producto guardado correctamente.", "success")
            return redirect(url_for("catalog.products"))
        except (ValueError, InvalidOperation) as error:
            db.session.rollback()
            flash(str(error), "error")
    return render_template("catalog/product_form.html", product=product,
                           categories=Category.query.filter_by(active=True).order_by(Category.name).all(),
                           brands=Brand.query.filter_by(active=True).order_by(Brand.name).all(),
                           suppliers=Supplier.query.filter_by(active=True).order_by(Supplier.name).all())


@bp.route("/categorias", methods=["GET", "POST"])
@login_required
@roles_required("admin", "warehouse")
def categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Escribe el nombre de la categoría.", "error")
        elif Category.query.filter_by(name=name).first():
            flash("Esa categoría ya existe.", "error")
        else:
            item = Category(name=name, description=request.form.get("description", "").strip(), active=True)
            db.session.add(item)
            audit("Categoría creada", name)
            db.session.commit()
            flash("Categoría creada.", "success")
            return redirect(url_for("catalog.categories"))
    rows = Category.query.order_by(Category.name).all()
    return render_template("catalog/taxonomy.html", title="Categorías", rows=rows, endpoint="catalog.categories", kind="categoría")


@bp.route("/marcas", methods=["GET", "POST"])
@login_required
@roles_required("admin", "warehouse")
def brands():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Escribe el nombre de la marca.", "error")
        elif Brand.query.filter_by(name=name).first():
            flash("Esa marca ya existe.", "error")
        else:
            db.session.add(Brand(name=name, active=True))
            audit("Marca creada", name)
            db.session.commit()
            flash("Marca creada.", "success")
            return redirect(url_for("catalog.brands"))
    rows = Brand.query.order_by(Brand.name).all()
    return render_template("catalog/taxonomy.html", title="Marcas", rows=rows, endpoint="catalog.brands", kind="marca")


@bp.post("/<any(categorias,marcas):kind>/<int:item_id>/estado")
@login_required
@roles_required("admin", "warehouse")
def toggle_taxonomy(kind, item_id):
    model = {"categorias": Category, "marcas": Brand}.get(kind)
    if not model:
        abort(404)
    item = db.get_or_404(model, item_id)
    item.active = not item.active
    audit("Estado actualizado", f"{kind[:-1]} {item.name}: {'activo' if item.active else 'inactivo'}")
    db.session.commit()
    flash("Estado actualizado.", "success")
    return redirect(url_for("catalog.categories" if kind == "categorias" else "catalog.brands"))


@bp.route("/<string:kind>", methods=["GET", "POST"])
@login_required
@roles_required("admin", "seller", "warehouse")
def directory(kind):
    config = {
        "proveedores": (Supplier, "Proveedor", ["name", "contact", "phone", "email", "nit", "address"]),
        "clientes": (Customer, "Cliente", ["name", "document", "phone", "email", "address"]),
    }.get(kind)
    if not config:
        abort(404)
    model, label, fields = config
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("El nombre es obligatorio.", "error")
        else:
            values = {field: request.form.get(field, "").strip() or None for field in fields}
            limits = {"name": 160, "contact": 120, "phone": 40, "email": 160, "nit": 40, "document": 40, "address": 255}
            if any(value and len(value) > limits[field] for field, value in values.items()):
                flash("Uno de los campos supera el máximo de caracteres permitido.", "error")
                return redirect(url_for("catalog.directory", kind=kind))
            if values.get("email"):
                try:
                    values["email"] = normalize_email(values["email"])
                except ValueError as error:
                    flash(str(error), "error")
                    return redirect(url_for("catalog.directory", kind=kind))
            item = model(**values, active=True)
            db.session.add(item)
            audit(f"{label} creado", name)
            db.session.commit()
            flash(f"{label} guardado.", "success")
            return redirect(url_for("catalog.directory", kind=kind))
    q = request.args.get("q", "").strip()
    query = model.query
    if q:
        query = query.filter(model.name.ilike(f"%{q}%"))
    page = query.order_by(model.name).paginate(page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    return render_template("catalog/directory.html", kind=kind, label=label, fields=fields, page=page, q=q)


@bp.post("/<any(proveedores,clientes):kind>/<int:item_id>/estado")
@login_required
@roles_required("admin")
def toggle_directory(kind, item_id):
    model = {"proveedores": Supplier, "clientes": Customer}.get(kind)
    if not model:
        abort(404)
    item = db.get_or_404(model, item_id)
    if isinstance(item, Customer) and item.is_default:
        flash("El cliente Consumidor final está protegido.", "error")
    else:
        item.active = not item.active
        audit("Estado actualizado", f"{kind[:-1]} {item.name}: {'activo' if item.active else 'inactivo'}")
        db.session.commit()
        flash("Estado actualizado.", "success")
    return redirect(url_for("catalog.directory", kind=kind))
