const menuItems = window.MENU_ITEMS || [];
const byKey = Object.fromEntries(menuItems.map((item) => [item.key, item]));
const selectedKeys = [];
const quantities = {};

const menuGrid = document.getElementById("menu-grid");
const selectionList = document.getElementById("selection-list");
const totalEl = document.getElementById("order-total");
const countEl = document.getElementById("order-count");
const submitBtn = document.getElementById("submit-order");
const statusBanner = document.getElementById("status-banner");

function centsToDollars(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}

function showStatus(message) {
  statusBanner.textContent = message;
  statusBanner.classList.add("show");
  clearTimeout(showStatus.timeoutId);
  showStatus.timeoutId = setTimeout(() => {
    statusBanner.classList.remove("show");
  }, 2200);
}

function renderMenu() {
  menuGrid.innerHTML = "";

  menuItems.forEach((item) => {
    const card = document.createElement("button");
    card.className = "menu-item";
    card.type = "button";
    card.innerHTML = `
      <img src="/assets/${item.image}" alt="${item.name} image placeholder" />
      <h3>${item.name}</h3>
      <p>${centsToDollars(item.price_cents)}</p>
      <span class="qty-badge" data-key="${item.key}" hidden>0</span>
    `;

    card.addEventListener("click", () => {
      selectedKeys.push(item.key);
      quantities[item.key] = (quantities[item.key] || 0) + 1;
      updateUi();
    });

    menuGrid.appendChild(card);
  });
}

function renderSelection() {
  const entries = Object.entries(quantities).filter(([, qty]) => qty > 0);

  if (!entries.length) {
    selectionList.innerHTML = '<p class="muted">No items selected yet.</p>';
    return;
  }

  selectionList.innerHTML = entries
    .map(([key, qty]) => {
      const item = byKey[key];
      return `
        <div class="selection-item">
          <span>${item.name} x ${qty}</span>
          <div class="selection-actions">
            <strong>${centsToDollars(item.price_cents * qty)}</strong>
            <button class="remove-item-btn" type="button" data-key="${key}" aria-label="Remove one ${item.name}">Remove</button>
          </div>
        </div>
      `;
    })
    .join("");
}

function updateBadges() {
  menuItems.forEach((item) => {
    const badge = document.querySelector(`.qty-badge[data-key="${item.key}"]`);
    const qty = quantities[item.key] || 0;
    badge.textContent = qty;
    badge.hidden = qty === 0;
  });
}

function updateSummary() {
  const summary = Object.entries(quantities).reduce(
    (acc, [key, quantity]) => {
      const item = byKey[key];
      if (!item || quantity <= 0) {
        return acc;
      }
      return {
        totalCents: acc.totalCents + item.price_cents * quantity,
        itemCount: acc.itemCount + quantity,
      };
    },
    { totalCents: 0, itemCount: 0 },
  );

  const { totalCents, itemCount } = summary;
  totalEl.textContent = centsToDollars(totalCents);
  countEl.textContent = `${itemCount} item${itemCount === 1 ? "" : "s"}`;
  submitBtn.disabled = itemCount === 0;
}

function updateUi() {
  updateBadges();
  updateSummary();
  renderSelection();
}

function removeOneItem(itemKey) {
  if (!quantities[itemKey]) {
    return;
  }

  quantities[itemKey] -= 1;
  if (quantities[itemKey] <= 0) {
    delete quantities[itemKey];
  }

  const index = selectedKeys.lastIndexOf(itemKey);
  if (index !== -1) {
    selectedKeys.splice(index, 1);
  }

  updateUi();
}

async function submitOrder() {
  submitBtn.disabled = true;
  try {
    const response = await fetch("/api/orders", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ items: selectedKeys }),
    });

    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : { error: await response.text() };
    if (!response.ok) {
      throw new Error(payload.error || "Failed to submit order.");
    }

    selectedKeys.length = 0;
    Object.keys(quantities).forEach((key) => {
      delete quantities[key];
    });
    updateUi();
    showStatus("Order saved to database.");
  } catch (error) {
    showStatus(error.message);
  } finally {
    submitBtn.disabled = Object.keys(quantities).length === 0;
  }
}

submitBtn.addEventListener("click", submitOrder);
selectionList.addEventListener("click", (event) => {
  const button = event.target.closest(".remove-item-btn");
  if (!button) {
    return;
  }
  removeOneItem(button.dataset.key);
});

renderMenu();
updateUi();
