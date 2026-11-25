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
from app.models import (
    AuditLog, Brand, Category, Customer, CustomerProfile, InventoryMovement,
    Product, Purchase, PurchaseLine, Sale, SaleLine, Supplier, SupplierProfile,
)
from app.security import roles_required
from app.validation import normalize_email

MAX_MONEY = Decimal("9999999999.99")
Image.MAX_IMAGE_PIXELS = 20_000_000
PRODUCT_IMAGE_CHOICES = (
    ("img/products/bateria-yuasa.webp", "Batería YUASA YTX7A-BS"),
    ("img/products/kit-arrastre-428h.webp", "Kit de arrastre 428H"),
    ("img/products/bujia-ngk-cr7e.webp", "Bujía NGK CR7E"),
    ("img/products/pastillas-freno.webp", "Pastillas de freno"),
    ("img/products/camara-aire.webp", "Cámara de aire 2.75-18"),
)
PRODUCT_IMAGE_PATHS = {path for path, _label in PRODUCT_IMAGE_CHOICES}


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


def remove_product_image(path):
    """Remove only files inside the product upload directory."""
    if not path or not path.startswith("uploads/products/"):
        return
    uploads = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    target = (Path(current_app.static_folder) / path).resolve()
    try:
        target.relative_to(uploads)
    except ValueError:
        return
    if target.is_file():
        target.unlink()


@bp.get("/productos")
@login_required
def products():
    q = request.args.get("q", "").strip()
    status = request.args.get("estado", "activos")
    if status not in {"activos", "inactivos", "todos"}:
        status = "activos"
    query = Product.query
    if status == "activos":
        query = query.filter(Product.active.is_(True))
    elif status == "inactivos":
        query = query.filter(Product.active.is_(False))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Product.name.ilike(like), Product.sku.ilike(like), Product.barcode.ilike(like), Product.model_reference.ilike(like)))
    page = query.order_by(Product.name.asc()).paginate(page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    return render_template("catalog/products.html", page=page, q=q, status=status)


@bp.route("/productos/nuevo", methods=["GET", "POST"])
@bp.route("/productos/<int:product_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("admin", "warehouse")
def product_form(product_id=None):
    product = db.get_or_404(Product, product_id) if product_id else Product(active=True)
    if request.method == "POST":
        try:
            original_category_id, original_brand_id, original_supplier_id = (
                product.category_id, product.brand_id, product.supplier_id
            )
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
                if not category or (not category.active and category.id != original_category_id):
                    raise ValueError("Selecciona una categoría activa.")
            if product.brand_id:
                brand = db.session.get(Brand, product.brand_id)
                if not brand or (not brand.active and brand.id != original_brand_id):
                    raise ValueError("Selecciona una marca activa.")
            if product.supplier_id:
                supplier = db.session.get(Supplier, product.supplier_id)
                if not supplier or (not supplier.active and supplier.id != original_supplier_id):
                    raise ValueError("Selecciona un proveedor activo.")
            is_new = product.id is None
            if is_new:
                product.stock = stock
            elif stock != product.stock:
                raise ValueError("Para modificar existencias usa el módulo Inventario, que deja el movimiento registrado.")
            uploaded = save_product_image(request.files.get("image"))
            old_image = product.image_path
            if uploaded:
                product.image_path = uploaded
            elif product.id and request.form.get("remove_image") == "1":
                product.image_path = None
            elif request.form.get("image_asset") in PRODUCT_IMAGE_PATHS:
                product.image_path = request.form.get("image_asset")
            db.session.add(product)
            db.session.flush()
            if is_new and stock:
                db.session.add(InventoryMovement(product_id=product.id, user_id=current_user.id,
                    movement_type="initial", quantity=stock, before_stock=0, after_stock=stock,
                    reason="Existencia inicial al registrar producto"))
            audit("Producto guardado", f"Producto {product.name} ({product.sku})", f"producto:{product.id}")
            db.session.commit()
            if old_image and old_image != product.image_path and not Product.query.filter_by(image_path=old_image).first():
                remove_product_image(old_image)
            flash("Producto guardado correctamente.", "success")
            return redirect(url_for("catalog.products"))
        except (ValueError, InvalidOperation) as error:
            db.session.rollback()
            flash(str(error), "error")
    return render_template("catalog/product_form.html", product=product,
                           categories=Category.query.filter(or_(Category.active.is_(True), Category.id == product.category_id)).order_by(Category.name).all(),
                           brands=Brand.query.filter(or_(Brand.active.is_(True), Brand.id == product.brand_id)).order_by(Brand.name).all(),
                           suppliers=Supplier.query.filter(or_(Supplier.active.is_(True), Supplier.id == product.supplier_id)).order_by(Supplier.name).all(),
                           product_images=PRODUCT_IMAGE_CHOICES)


@bp.post("/productos/<int:product_id>/eliminar")
@login_required
@roles_required("admin", "warehouse")
def delete_product(product_id):
    product = db.get_or_404(Product, product_id)
    image_path = product.image_path
    has_history = (
        InventoryMovement.query.filter_by(product_id=product.id).first()
        or SaleLine.query.filter_by(product_id=product.id).first()
        or PurchaseLine.query.filter_by(product_id=product.id).first()
    )
    if has_history or product.stock > 0:
        product.active = False
        audit("Producto archivado", f"Producto {product.name} ({product.sku}); se conservó su historial", f"producto:{product.id}")
        db.session.commit()
        flash("El producto tenía existencias o movimientos; quedó inactivo para conservar el historial.", "success")
    else:
        name = product.name
        db.session.delete(product)
        audit("Producto eliminado", f"Producto {name} ({product.sku})")
        db.session.commit()
        if image_path and not Product.query.filter_by(image_path=image_path).first():
            remove_product_image(image_path)
        flash("Producto eliminado.", "success")
    return redirect(url_for("catalog.products", estado=request.args.get("estado", "activos")))


@bp.post("/productos/<int:product_id>/estado")
@login_required
@roles_required("admin", "warehouse")
def toggle_product(product_id):
    product = db.get_or_404(Product, product_id)
    product.active = not product.active
    audit("Estado actualizado", f"Producto {product.name}: {'activo' if product.active else 'inactivo'}", f"producto:{product.id}")
    db.session.commit()
    flash("Producto activado." if product.active else "Producto desactivado.", "success")
    return redirect(url_for("catalog.products", estado=request.args.get("estado", "activos")))


def taxonomy_page(model, title, kind, route_name):
    edit_id = request.args.get("editar", type=int)
    editing = db.session.get(model, edit_id) if edit_id else None
    if edit_id and not editing:
        abort(404)
    form_data = None
    if request.method == "POST":
        item_id = request.form.get("item_id", type=int)
        item = db.session.get(model, item_id) if item_id else model(active=True)
        if item_id and not item:
            abort(404)
        name = request.form.get("name", "").strip()
        if not name:
            flash(f"Escribe el nombre de la {kind}.", "error")
        elif len(name) > 100:
            flash("El nombre supera los 100 caracteres permitidos.", "error")
        elif model.query.filter(model.name == name, model.id != (item.id or 0)).first():
            flash(f"Ya existe una {kind} con ese nombre.", "error")
        else:
            item.name = name
            if model is Category:
                item.description = request.form.get("description", "").strip() or None
            db.session.add(item)
            audit(f"{kind.title()} {'actualizada' if item_id else 'creada'}", name, f"{kind}:{item.id}" if item_id else None)
            db.session.commit()
            flash(f"{kind.title()} {'actualizada' if item_id else 'creada'} correctamente.", "success")
            return redirect(url_for(route_name))
        editing = item if item_id else None
        form_data = request.form
    rows = model.query.order_by(model.name).all()
    return render_template("catalog/taxonomy.html", title=title, rows=rows, endpoint=route_name,
                           kind=kind, editing=editing, form_data=form_data)


@bp.route("/categorias", methods=["GET", "POST"])
@login_required
@roles_required("admin", "warehouse")
def categories():
    return taxonomy_page(Category, "Categorías", "categoría", "catalog.categories")


@bp.route("/marcas", methods=["GET", "POST"])
@login_required
@roles_required("admin", "warehouse")
def brands():
    return taxonomy_page(Brand, "Marcas", "marca", "catalog.brands")


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


@bp.post("/<any(categorias,marcas):kind>/<int:item_id>/eliminar")
@login_required
@roles_required("admin", "warehouse")
def delete_taxonomy(kind, item_id):
    model = {"categorias": Category, "marcas": Brand}.get(kind)
    item = db.get_or_404(model, item_id)
    used = Product.query.filter(
        (Product.category_id == item.id) if model is Category else (Product.brand_id == item.id)
    ).first()
    destination = "catalog.categories" if kind == "categorias" else "catalog.brands"
    if used:
        item.active = False
        audit("Elemento archivado", f"{kind[:-1]} {item.name}; usado por productos", f"{kind[:-1]}:{item.id}")
        db.session.commit()
        flash(f"{kind[:-1].capitalize()} en uso: se desactivó para conservar los productos asociados.", "success")
    else:
        name = item.name
        db.session.delete(item)
        audit(f"{kind[:-1].capitalize()} eliminada", name)
        db.session.commit()
        flash(f"{kind[:-1].capitalize()} eliminada.", "success")
    return redirect(url_for(destination))


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
    editing = None
    profile_data = None
    if request.method == "POST":
        item_id = request.form.get("edit_id", type=int)
        item = db.session.get(model, item_id) if item_id else model()
        if item_id and not item:
            abort(404)
        if isinstance(item, Customer) and item.is_default:
            flash("El cliente Consumidor final está protegido.", "error")
            return redirect(url_for("catalog.directory", kind=kind))
        name = request.form.get("name", "").strip()
        if not name:
            flash("El nombre es obligatorio.", "error")
            editing, profile_data = item, request.form
        else:
            values = {field: request.form.get(field, "").strip() or None for field in fields}
            limits = {"name": 160, "contact": 120, "phone": 40, "email": 160, "nit": 40, "document": 40, "address": 255}
            extra_limits = {"brands": 255, "terms": 100, "motorcycle": 160, "notes": 255}
            invalid_lengths = any(value and len(value) > limits[field] for field, value in values.items())
            invalid_extra_lengths = any(len(request.form.get(field, "").strip()) > limit for field, limit in extra_limits.items())
            if invalid_lengths:
                flash("Uno de los campos supera el máximo de caracteres permitido.", "error")
                editing, profile_data = item, request.form
            elif invalid_extra_lengths:
                flash("Uno de los datos complementarios supera el máximo de caracteres permitido.", "error")
                editing, profile_data = item, request.form
            elif values.get("email"):
                try:
                    values["email"] = normalize_email(values["email"])
                except ValueError as error:
                    flash(str(error), "error")
                    editing, profile_data = item, request.form
            if profile_data is None:
                for field, value in values.items():
                    setattr(item, field, value)
                if item_id is None:
                    item.active = True
                db.session.add(item)
                db.session.flush()
                if kind == "proveedores":
                    profile = item.profile or SupplierProfile(supplier_id=item.id)
                    profile.brands = request.form.get("brands", "").strip() or None
                    profile.terms = request.form.get("terms", "").strip() or None
                    profile.supplier = item
                else:
                    profile = item.profile or CustomerProfile(customer_id=item.id)
                    profile.motorcycle = request.form.get("motorcycle", "").strip() or None
                    profile.notes = request.form.get("notes", "").strip() or None
                    profile.demo = request.form.get("demo") == "1"
                    profile.customer = item
                db.session.add(profile)
                audit(f"{label} {'actualizado' if item_id else 'creado'}", item.name, f"{kind}:{item.id}")
                db.session.commit()
                flash(f"{label} {'actualizado' if item_id else 'guardado'} correctamente.", "success")
                return redirect(url_for("catalog.directory", kind=kind))
    elif request.args.get("editar", type=int):
        editing = db.session.get(model, request.args.get("editar", type=int))
        if not editing:
            abort(404)
        if isinstance(editing, Customer) and editing.is_default:
            flash("El cliente Consumidor final está protegido.", "error")
            return redirect(url_for("catalog.directory", kind=kind))
    q = request.args.get("q", "").strip()
    query = model.query
    if q:
        query = query.filter(model.name.ilike(f"%{q}%"))
    page = query.order_by(model.name).paginate(page=request.args.get("page", 1, type=int), per_page=20, error_out=False)
    return render_template("catalog/directory.html", kind=kind, label=label, fields=fields, page=page, q=q,
                           editing=editing, profile_data=profile_data)


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


@bp.post("/<any(proveedores,clientes):kind>/<int:item_id>/eliminar")
@login_required
@roles_required("admin")
def delete_directory(kind, item_id):
    model = {"proveedores": Supplier, "clientes": Customer}.get(kind)
    item = db.get_or_404(model, item_id)
    if isinstance(item, Customer) and item.is_default:
        flash("El cliente Consumidor final está protegido.", "error")
        return redirect(url_for("catalog.directory", kind=kind))
    if isinstance(item, Supplier):
        in_use = Purchase.query.filter_by(supplier_id=item.id).first() or Product.query.filter_by(supplier_id=item.id).first()
    else:
        in_use = Sale.query.filter_by(customer_id=item.id).first()
    if in_use:
        item.active = False
        audit("Registro archivado", f"{label_for_kind(kind)} {item.name}; tiene operaciones relacionadas", f"{kind}:{item.id}")
        db.session.commit()
        flash(f"{item.name} tiene operaciones relacionadas; se desactivó para conservar el historial.", "success")
    else:
        audit("Registro eliminado", f"{label_for_kind(kind)} {item.name}", f"{kind}:{item.id}")
        db.session.delete(item)
        db.session.commit()
        flash(f"{label_for_kind(kind)} eliminado.", "success")
    return redirect(url_for("catalog.directory", kind=kind))


def label_for_kind(kind):
    return "Proveedor" if kind == "proveedores" else "Cliente"
