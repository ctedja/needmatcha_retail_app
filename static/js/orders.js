const menuItems = window.MENU_ITEMS || [];
const byKey = Object.fromEntries(menuItems.map((item) => [item.key, item]));
const listEl = document.getElementById("orders-list");
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

function formatTimestamp(isoString) {
  const date = new Date(isoString);
  return date.toLocaleString();
}

function menuOptions(selectedKey) {
  return menuItems
    .map((item) => {
      const selected = item.key === selectedKey ? "selected" : "";
      return `<option value="${item.key}" ${selected}>${item.name}</option>`;
    })
    .join("");
}

function orderCard(order) {
  const item = byKey[order.item_key] || {};
  return `
    <article class="record-card" data-id="${order.id}">
      <div class="record-meta">
        <span>#${order.id}</span>
        <span>${formatTimestamp(order.ordered_at)}</span>
      </div>
      <div class="record-body">
        <img src="/assets/${item.image || "sachet.png"}" alt="${order.item_name} image placeholder" />
        <div>
          <h3>${order.item_name}</h3>
          <p>${centsToDollars(order.price_cents)}</p>
        </div>
      </div>
      <div class="record-actions">
        <select aria-label="Item type">${menuOptions(order.item_key)}</select>
        <button class="btn-update" type="button">Save</button>
        <button class="btn-delete" type="button">Delete</button>
      </div>
    </article>
  `;
}

async function fetchOrders() {
  const response = await fetch("/api/orders");
  if (!response.ok) {
    throw new Error("Unable to load database records.");
  }
  return response.json();
}

async function renderOrders() {
  try {
    const orders = await fetchOrders();
    if (!orders.length) {
      listEl.innerHTML = '<p class="muted">No records yet.</p>';
      return;
    }
    listEl.innerHTML = orders.map(orderCard).join("");
  } catch (error) {
    listEl.innerHTML = `<p class="muted">${error.message}</p>`;
  }
}

async function updateOrder(orderId, itemKey) {
  const response = await fetch(`/api/orders/${orderId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_key: itemKey }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Unable to update record.");
  }
}

async function deleteOrder(orderId) {
  const response = await fetch(`/api/orders/${orderId}`, { method: "DELETE" });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Unable to delete record.");
  }
}

listEl.addEventListener("click", async (event) => {
  const card = event.target.closest(".record-card");
  if (!card) {
    return;
  }

  const orderId = card.dataset.id;
  const selectEl = card.querySelector("select");

  try {
    if (event.target.classList.contains("btn-update")) {
      await updateOrder(orderId, selectEl.value);
      showStatus("Record updated.");
      await renderOrders();
      return;
    }

    if (event.target.classList.contains("btn-delete")) {
      await deleteOrder(orderId);
      showStatus("Record deleted.");
      await renderOrders();
    }
  } catch (error) {
    showStatus(error.message);
  }
});

renderOrders();
