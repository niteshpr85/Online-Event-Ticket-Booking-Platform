const outputs = {
  admin: document.getElementById("adminOutput"),
  organizer: document.getElementById("organizerOutput"),
  customer: document.getElementById("customerOutput"),
  entry: document.getElementById("entryOutput"),
  support: document.getElementById("supportOutput"),
};

const eventsList = document.getElementById("eventsList");

function showOut(target, data) {
  outputs[target].textContent = JSON.stringify(data, null, 2);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.detail || JSON.stringify(body));
  }
  return body;
}

function toInt(value) {
  if (!value) return null;
  return Number.parseInt(value, 10);
}

async function loadEvents() {
  const events = await api("/api/events");
  eventsList.innerHTML = "";
  events.forEach((event) => {
    const card = document.createElement("div");
    card.className = "event-card";
    const btn = document.createElement("button");
    btn.textContent = "View Seats";
    btn.addEventListener("click", async () => {
      try {
        const seats = await api(`/api/events/${event.id}/seats`);
        showOut("customer", {
          event_id: event.id,
          available_seat_ids: seats.filter((s) => s.is_available).map((s) => s.id),
          seats,
        });
      } catch (err) {
        showOut("customer", { error: err.message });
      }
    });
    card.innerHTML = `
      <strong>${event.title}</strong><br>
      <span>${event.venue}</span><br>
      <span>Status: ${event.status}</span><br>
      <span>Seats: ${event.available_seats}/${event.total_seats}</span><br>
      <span>Base Price: ${event.base_price}</span>
    `;
    card.appendChild(document.createElement("br"));
    card.appendChild(btn);
    eventsList.appendChild(card);
  });
}

document.getElementById("loadUsersBtn").addEventListener("click", async () => {
  try {
    showOut("admin", await api("/api/users"));
  } catch (err) {
    showOut("admin", { error: err.message });
  }
});

document.getElementById("loadAnalyticsBtn").addEventListener("click", async () => {
  try {
    showOut("admin", await api("/api/analytics"));
  } catch (err) {
    showOut("admin", { error: err.message });
  }
});

document.getElementById("createEventForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = {
    organizer_id: toInt(fd.get("organizer_id")),
    title: fd.get("title"),
    description: fd.get("description"),
    venue: fd.get("venue"),
    start_time: new Date(fd.get("start_time")).toISOString(),
    end_time: new Date(fd.get("end_time")).toISOString(),
    base_price: Number(fd.get("base_price")),
    row_count: toInt(fd.get("row_count")),
    seats_per_row: toInt(fd.get("seats_per_row")),
  };
  try {
    const result = await api("/api/events", { method: "POST", body: JSON.stringify(payload) });
    showOut("organizer", result);
    await loadEvents();
  } catch (err) {
    showOut("organizer", { error: err.message });
  }
});

document.getElementById("eventStatusForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const eventId = toInt(fd.get("event_id"));
  const payload = { status: fd.get("status") };
  try {
    const result = await api(`/api/events/${eventId}/status`, { method: "PATCH", body: JSON.stringify(payload) });
    showOut("organizer", result);
    await loadEvents();
  } catch (err) {
    showOut("organizer", { error: err.message });
  }
});

document.getElementById("refreshEventsBtn").addEventListener("click", async () => {
  try {
    await loadEvents();
    showOut("customer", { ok: true, message: "Events refreshed" });
  } catch (err) {
    showOut("customer", { error: err.message });
  }
});

document.getElementById("loadOffersBtn").addEventListener("click", async () => {
  try {
    showOut("customer", await api("/api/offers"));
  } catch (err) {
    showOut("customer", { error: err.message });
  }
});

document.getElementById("createBookingForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const seatIds = fd
    .get("seat_ids")
    .split(",")
    .map((v) => Number.parseInt(v.trim(), 10))
    .filter((n) => !Number.isNaN(n));

  const payload = {
    customer_id: toInt(fd.get("customer_id")),
    event_id: toInt(fd.get("event_id")),
    seat_ids: seatIds,
    offer_code: fd.get("offer_code") || null,
  };
  try {
    const result = await api("/api/bookings", { method: "POST", body: JSON.stringify(payload) });
    showOut("customer", result);
    await loadEvents();
  } catch (err) {
    showOut("customer", { error: err.message });
  }
});

document.getElementById("payBookingForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const bookingId = toInt(fd.get("booking_id"));
  const payload = {
    customer_id: toInt(fd.get("customer_id")),
    method: fd.get("method"),
    mark_success: fd.get("mark_success") === "true",
  };
  try {
    const result = await api(`/api/bookings/${bookingId}/pay`, { method: "POST", body: JSON.stringify(payload) });
    showOut("customer", result);
    await loadEvents();
  } catch (err) {
    showOut("customer", { error: err.message });
  }
});

document.getElementById("refundRequestForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const bookingId = toInt(fd.get("booking_id"));
  const payload = {
    customer_id: toInt(fd.get("customer_id")),
    reason: fd.get("reason"),
  };
  try {
    const result = await api(`/api/bookings/${bookingId}/refund-request`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showOut("customer", result);
    await loadEvents();
  } catch (err) {
    showOut("customer", { error: err.message });
  }
});

document.getElementById("complaintForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = {
    customer_id: toInt(fd.get("customer_id")),
    booking_id: toInt(fd.get("booking_id")),
    event_id: toInt(fd.get("event_id")),
    subject: fd.get("subject"),
    description: fd.get("description"),
  };
  try {
    showOut("customer", await api("/api/complaints", { method: "POST", body: JSON.stringify(payload) }));
  } catch (err) {
    showOut("customer", { error: err.message });
  }
});

document.getElementById("loadHistoryBtn").addEventListener("click", async () => {
  const customerId = toInt(document.getElementById("historyCustomerId").value);
  try {
    showOut("customer", await api(`/api/customers/${customerId}/bookings`));
  } catch (err) {
    showOut("customer", { error: err.message });
  }
});

document.getElementById("validateTicketForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const payload = {
    entry_manager_id: toInt(fd.get("entry_manager_id")),
    qr_code: fd.get("qr_code"),
  };
  try {
    showOut("entry", await api("/api/tickets/validate", { method: "POST", body: JSON.stringify(payload) }));
  } catch (err) {
    showOut("entry", { error: err.message });
  }
});

document.getElementById("loadComplaintsBtn").addEventListener("click", async () => {
  try {
    showOut("support", await api("/api/complaints"));
  } catch (err) {
    showOut("support", { error: err.message });
  }
});

document.getElementById("complaintUpdateForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const complaintId = toInt(fd.get("complaint_id"));
  const payload = {
    support_executive_id: toInt(fd.get("support_executive_id")),
    status: fd.get("status"),
    resolution: fd.get("resolution") || null,
  };
  try {
    showOut("support", await api(`/api/complaints/${complaintId}`, { method: "PATCH", body: JSON.stringify(payload) }));
  } catch (err) {
    showOut("support", { error: err.message });
  }
});

document.getElementById("refundDecisionForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const bookingId = toInt(fd.get("booking_id"));
  const payload = {
    support_executive_id: toInt(fd.get("support_executive_id")),
    approve: fd.get("approve") === "true",
  };
  try {
    showOut("support", await api(`/api/bookings/${bookingId}/refund-decision`, { method: "POST", body: JSON.stringify(payload) }));
    await loadEvents();
  } catch (err) {
    showOut("support", { error: err.message });
  }
});

(async () => {
  try {
    await loadEvents();
  } catch (err) {
    showOut("customer", { error: err.message });
  }
})();
