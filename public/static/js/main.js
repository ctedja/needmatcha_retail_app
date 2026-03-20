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
const SUBMIT_TIMEOUT_MS = 45000;
let pendingRequestId = null;
let pendingFingerprint = null;

function createRequestId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  if (window.crypto && typeof window.crypto.getRandomValues === "function") {
    const bytes = new Uint8Array(16);
    window.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = Math.floor(Math.random() * 16);
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function cartFingerprint() {
  return selectedKeys.join("|");
}

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
  const fingerprint = cartFingerprint();
  if (!pendingRequestId || pendingFingerprint !== fingerprint) {
    pendingRequestId = createRequestId();
    pendingFingerprint = fingerprint;
  }
  const requestId = pendingRequestId;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), SUBMIT_TIMEOUT_MS);
  try {
    const response = await fetch("/api/orders", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": requestId,
      },
      body: JSON.stringify({ items: selectedKeys }),
      signal: controller.signal,
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
    pendingRequestId = null;
    pendingFingerprint = null;
    showStatus(payload.idempotent_replay ? "Order already saved." : "Order saved to database.");
  } catch (error) {
    const message =
      error.name === "AbortError"
        ? "Submit timed out. Check orders page before retrying."
        : error.message;
    showStatus(message);
  } finally {
    clearTimeout(timeoutId);
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
