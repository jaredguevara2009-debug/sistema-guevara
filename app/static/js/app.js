(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const sidebar = $("#sidebar");
  const shade = $(".mobile-shade");
  const closeNav = () => { sidebar?.classList.remove("nav-open"); shade?.classList.remove("visible"); };
  $("[data-menu-toggle]")?.addEventListener("click", () => {
    sidebar?.classList.toggle("nav-open"); shade?.classList.toggle("visible");
  });
  shade?.addEventListener("click", closeNav);
  $$('[data-close-nav]').forEach((node) => node.addEventListener("click", closeNav));

  $$('[data-dismiss]').forEach((button) => button.addEventListener("click", () => button.closest(".flash")?.remove()));
  $$('[data-confirm]').forEach((form) => form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  $("[data-password-toggle]")?.addEventListener("click", (event) => {
    const input = $("#password");
    if (!input) return;
    input.type = input.type === "password" ? "text" : "password";
    event.currentTarget.setAttribute("aria-label", input.type === "password" ? "Mostrar contraseña" : "Ocultar contraseña");
  });
  $("[data-print]")?.addEventListener("click", () => window.print());
  $("[data-loading-form]")?.addEventListener("submit", (event) => {
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    form.querySelector("button[type=submit]")?.classList.add("is-loading");
  });
  const productImageInput = $("[data-image-input]");
  const productImageSelect = $("[data-image-asset]");
  const productImagePreview = $("[data-image-preview]");
  const initialProductPreview = productImagePreview?.innerHTML;
  productImageInput?.addEventListener("change", (event) => {
    const file = event.currentTarget.files?.[0];
    if (!file || !productImagePreview || !file.type.startsWith("image/")) return;
    if (productImageSelect) productImageSelect.value = "";
    const image = document.createElement("img");
    image.alt = "Vista previa del producto";
    image.src = URL.createObjectURL(file);
    productImagePreview.replaceChildren(image);
  });
  productImageSelect?.addEventListener("change", (event) => {
    if (!productImagePreview) return;
    if (productImageInput) productImageInput.value = "";
    const option = event.currentTarget.selectedOptions[0];
    const source = option?.dataset.preview;
    if (!source) {
      productImagePreview.innerHTML = initialProductPreview || "";
      return;
    }
    const image = document.createElement("img");
    image.alt = "Vista previa del producto";
    image.src = source;
    productImagePreview.replaceChildren(image);
  });

  const categoryField = $("[data-category-field]");
  const brandField = $("[data-brand-field]");
  const filterBrandsByCategory = () => {
    if (!categoryField || !brandField) return;
    const categoryId = categoryField.value;
    [...brandField.options].forEach((option) => {
      if (!option.value || !categoryId) {
        option.hidden = false;
        option.disabled = false;
        return;
      }
      const categoryIds = (option.dataset.categoryIds || "").split(",").filter(Boolean);
      const compatible = categoryIds.includes(categoryId);
      option.hidden = !compatible;
      option.disabled = !compatible;
      if (!compatible && option.selected) brandField.value = "";
    });
  };
  categoryField?.addEventListener("change", filterBrandsByCategory);
  filterBrandsByCategory();

  const canvas = $("#sales-chart");
  if (canvas) {
    const labels = JSON.parse(canvas.dataset.labels || "[]");
    const values = JSON.parse(canvas.dataset.values || "[]");
    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      const ctx = canvas.getContext("2d");
      ctx.scale(dpr, dpr);
      const w = rect.width, h = rect.height;
      const left = 37, right = 8, top = 12, bottom = 27;
      const plotW = w - left - right, plotH = h - top - bottom;
      const max = Math.max(1, ...values);
      ctx.font = "10px DM Sans, Arial";
      ctx.textBaseline = "middle";
      for (let i = 0; i <= 3; i++) {
        const y = top + (plotH * i / 3);
        ctx.strokeStyle = "#eff0f3"; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(w - right, y); ctx.stroke();
        ctx.fillStyle = "#a2a6ae";
        const label = max === 0 ? "0" : Math.round(max * (3 - i) / 3).toLocaleString("es-BO");
        ctx.textAlign = "right"; ctx.fillText(label, left - 7, y);
      }
      const points = values.map((value, index) => ({
        x: left + (labels.length <= 1 ? plotW / 2 : plotW * index / (labels.length - 1)),
        y: top + plotH - (value / max) * plotH,
      }));
      if (points.length) {
        const gradient = ctx.createLinearGradient(0, top, 0, top + plotH);
        gradient.addColorStop(0, "rgba(230,57,70,.15)"); gradient.addColorStop(1, "rgba(230,57,70,0)");
        ctx.beginPath(); ctx.moveTo(points[0].x, top + plotH);
        points.forEach((point) => ctx.lineTo(point.x, point.y));
        ctx.lineTo(points.at(-1).x, top + plotH); ctx.closePath(); ctx.fillStyle = gradient; ctx.fill();
        ctx.beginPath(); points.forEach((point, index) => index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y));
        ctx.strokeStyle = "#e63946"; ctx.lineWidth = 2; ctx.lineJoin = "round"; ctx.stroke();
        points.forEach((point, index) => {
          ctx.beginPath(); ctx.arc(point.x, point.y, index === points.length - 1 ? 3.5 : 2.5, 0, Math.PI * 2);
          ctx.fillStyle = "#fff"; ctx.fill(); ctx.strokeStyle = "#e63946"; ctx.lineWidth = 1.5; ctx.stroke();
        });
      }
      labels.forEach((label, index) => {
        const x = left + (labels.length <= 1 ? plotW / 2 : plotW * index / (labels.length - 1));
        ctx.fillStyle = "#9b9fa8"; ctx.textAlign = "center"; ctx.fillText(label, x, h - 10);
      });
    };
    new ResizeObserver(draw).observe(canvas);
    draw();
  }

  const pos = $("[data-pos]");
  if (pos) {
    const cart = new Map();
    const cartRoot = $("[data-cart-items]", pos);
    const hiddenCart = $("[data-cart-json]", pos);
    const discountField = $("[data-discount]", pos);
    const money = (value) => `Bs ${Number(value || 0).toLocaleString("es-BO", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    const renderCart = () => {
      const lines = [...cart.values()];
      cartRoot.replaceChildren();
      if (!lines.length) {
        const empty = document.createElement("div"); empty.className = "cart-empty";
        empty.innerHTML = "<span>▱</span><strong>El carrito está vacío</strong><small>Selecciona productos del catálogo.</small>";
        cartRoot.append(empty);
      }
      let subtotal = 0, count = 0;
      lines.forEach((item) => {
        subtotal += Number(item.price) * item.qty; count += item.qty;
        const row = document.createElement("div"); row.className = "cart-line";
        const image = document.createElement(item.image ? "img" : "span"); image.className = "cart-line-image";
        if (item.image) { image.src = item.image; image.alt = ""; } else image.textContent = "▦";
        const copy = document.createElement("span"); copy.className = "cart-line-copy";
        const title = document.createElement("strong"); title.textContent = item.name;
        const sku = document.createElement("small"); sku.textContent = item.sku;
        const price = document.createElement("b"); price.textContent = money(Number(item.price) * item.qty);
        copy.append(title, sku, price);
        const qty = document.createElement("span"); qty.className = "qty-control";
        [["−", "decrease"], [String(item.qty), "quantity"], ["+", "increase"]].forEach(([text, action]) => {
          if (action === "quantity") { const countNode = document.createElement("span"); countNode.textContent = text; qty.append(countNode); }
          else { const button = document.createElement("button"); button.type = "button"; button.dataset.cartAction = action; button.dataset.id = item.id; button.textContent = text; qty.append(button); }
        });
        row.append(image, copy, qty); cartRoot.append(row);
      });
      const rawDiscount = Math.max(0, Number(discountField.value || 0));
      const limit = subtotal * (document.body.dataset.role === "admin" ? .2 : .05);
      const discount = Math.min(rawDiscount, limit, subtotal);
      $("[data-cart-count]").textContent = String(count);
      $("[data-subtotal]").textContent = money(subtotal);
      $("[data-discount-total]").textContent = money(discount);
      $("[data-grand-total]").textContent = money(subtotal - discount);
      hiddenCart.value = JSON.stringify(lines.map(({ id, qty }) => ({ id, qty })));
    };
    pos.addEventListener("click", (event) => {
      const add = event.target.closest("[data-add-product]");
      if (add) {
        const id = add.dataset.id;
        const current = cart.get(id);
        const nextQty = (current?.qty || 0) + 1;
        if (nextQty > Number(add.dataset.stock)) return;
        cart.set(id, { id: Number(id), qty: nextQty, name: add.dataset.name, sku: add.dataset.sku, price: Number(add.dataset.price), stock: Number(add.dataset.stock), image: add.dataset.image });
        renderCart();
        return;
      }
      const action = event.target.closest("[data-cart-action]");
      if (action) {
        const id = action.dataset.id, item = cart.get(id);
        if (!item) return;
        const nextQty = item.qty + (action.dataset.cartAction === "increase" ? 1 : -1);
        if (nextQty < 1) cart.delete(id); else if (nextQty <= item.stock) item.qty = nextQty;
        renderCart();
      }
    });
    $("[data-cart-clear]", pos)?.addEventListener("click", () => { cart.clear(); renderCart(); });
    discountField?.addEventListener("input", renderCart);
    $("[data-product-search]", pos)?.addEventListener("input", (event) => {
      const query = event.currentTarget.value.trim().toLowerCase();
      $$('[data-add-product]', pos).forEach((product) => { product.hidden = !product.dataset.search.includes(query); });
    });
    $("[data-checkout-form]", pos)?.addEventListener("submit", (event) => {
      if (!cart.size) { event.preventDefault(); window.alert("Agrega al menos un producto al carrito."); return; }
      const key = $("[data-idempotency]", pos);
      if (!key.value) key.value = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      event.currentTarget.querySelector("button[type=submit]").disabled = true;
    });
    renderCart();
  }

  const purchaseForm = $("[data-purchase-form]");
  if (purchaseForm) {
    const cart = new Map();
    const productSelect = $("[data-purchase-product]", purchaseForm);
    const qtyInput = $("[data-purchase-qty]", purchaseForm);
    const costInput = $("[data-purchase-cost]", purchaseForm);
    const rows = $("[data-purchase-lines]", purchaseForm);
    const hidden = $("[data-purchase-json]", purchaseForm);
    const money = (value) => `Bs ${Number(value || 0).toLocaleString("es-BO", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    const render = () => {
      rows.replaceChildren(); let total = 0;
      if (!cart.size) {
        const tr = document.createElement("tr"), td = document.createElement("td"); td.colSpan = 5;
        const empty = document.createElement("div"); empty.className = "empty-state compact"; empty.textContent = "Agrega productos para armar la compra."; td.append(empty); tr.append(td); rows.append(tr);
      }
      cart.forEach((item, id) => {
        const subtotal = item.qty * item.cost; total += subtotal;
        const tr = document.createElement("tr");
        [item.name, String(item.qty), money(item.cost), money(subtotal)].forEach((text, index) => {
          const td = document.createElement("td"); td.textContent = text;
          if (index === 0) td.className = "table-primary";
          tr.append(td);
        });
        const actionCell = document.createElement("td"), remove = document.createElement("button");
        remove.type = "button"; remove.className = "text-button"; remove.textContent = "Quitar";
        remove.addEventListener("click", () => { cart.delete(id); render(); }); actionCell.append(remove); tr.append(actionCell); rows.append(tr);
      });
      $$("[data-purchase-total]")[0].textContent = money(total);
      hidden.value = JSON.stringify([...cart.values()].map(({ id, qty, cost }) => ({ id: Number(id), qty, cost })));
    };
    $("[data-purchase-add]", purchaseForm)?.addEventListener("click", () => {
      const option = productSelect.selectedOptions[0], id = productSelect.value;
      const qty = Number(qtyInput.value), cost = Number(costInput.value);
      if (!id || !Number.isInteger(qty) || qty < 1 || costInput.value.trim() === "" || !Number.isFinite(cost) || cost < 0) { window.alert("Selecciona un producto y revisa la cantidad y el costo."); return; }
      const item = cart.get(id) || { id, qty: 0, cost, name: option.dataset.name, sku: option.dataset.sku };
      item.qty += qty; item.cost = cost; cart.set(id, item); render();
    });
    purchaseForm.addEventListener("submit", (event) => {
      if (!cart.size) { event.preventDefault(); window.alert("Agrega al menos un producto a la compra."); }
    });
    render();
  }
})();
