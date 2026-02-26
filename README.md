<<<<<<< HEAD
# Online-Event-Ticket-Booking-Platform


Python + SQLite + Streamlit implementation of a role-based ticketing system.

## Tech Stack

- App Framework/UI: Streamlit
- ORM/Database: SQLAlchemy + SQLite
- Service/API layer: FastAPI-compatible service code (reused by Streamlit)

## Roles Implemented

- Platform Admin
- Event Organizer
- Customer
- Entry Manager
- Support Executive

## Features Implemented

- Login page (email/password)
- Register page (customer, event organizer, or platform admin)
- Forgot password + reset password flow (token-based)
- Event onboarding (organizer creates events + auto seat inventory)
- Seat inventory management (availability updates in real-time after booking/payment/refund)
- Booking flow with seat selection and offer code support
- Payment simulation (success/failure)
- Ticket issuance with QR-like code simulation
- Entry validation by entry manager (single-use enforcement)
- Refund request + support decision workflow
- Support complaint workflow
- Event cancellation logic (optional extension)
- Booking history endpoint and UI action (optional extension)
- Simple analytics endpoint (optional extension)
- Ticket download simulation endpoint (optional extension)
- Booking confirmation email simulation endpoint (optional extension)
- Event detail email notification (SMTP or simulation fallback)
- AI chatbot in Streamlit (OpenAI-backed with fallback mode)

## Project Structure

```txt
ticket/
  app/
    config.py
    db.py
    main.py
    models.py
    routes.py
    schemas.py
    services.py
  streamlit_app.py
  requirements.txt
  README.md
```

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the Streamlit app:

```bash
streamlit run streamlit_app.py
```

4. Open:

```txt
http://localhost:8501
```

On first startup, tables are created and demo seed data is inserted.

Optional: run FastAPI API server too (if needed):

```bash
uvicorn app.main:app --reload
```

## Email Configuration (Optional for Real SMTP)

If SMTP variables are not set, email actions run in simulation mode and return the composed email body.
For forgot-password, simulation mode returns a temporary reset token in the response/UI for demo use.

- `SMTP_HOST`
- `SMTP_PORT` (default: `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM_EMAIL` (default: `noreply@ticket.local`)
- `SMTP_USE_TLS` (default: `true`)
- `SMTP_USE_SSL` (default: `false`)

## AI Chatbot Configuration (Optional for OpenAI Mode)

If OpenAI variables are not set, chatbot works in fallback mode.

- `OPENAI_API_KEY`
- `OPENAI_MODEL` (default: `gpt-4.1-mini`)

## Seed Users

- `1` -> Platform Admin
- `2` -> Event Organizer
- `3` -> Customer
- `4` -> Entry Manager
- `5` -> Support Executive

## Seed Login Credentials

- `admin@ticket.local / admin123`
- `organizer@ticket.local / organizer123`
- `customer@ticket.local / customer123`
- `entry@ticket.local / entry123`
- `support@ticket.local / support123`

## Relational Schema Summary

- `users` (1-to-many) `events`
- `events` (1-to-many) `seats`
- `bookings` links `customers` and `events`
- `booking_seats` is the junction table between `bookings` and `seats`
- `payments` (1-to-1) `bookings`
- `tickets` (1-to-1) `booking_seats`
- `refunds` (1-to-1) `bookings`
- `support_tickets` linked to customer, optional booking, optional event
- `offers` used during booking pricing

## Streamlit UI Modules

- Simplified role-based sidebar navigation (one section visible at a time)
- Customer sections: Book Tickets, Payments, Refunds, Complaints, Event Email
- Organizer section: create event and update status
- Entry section: ticket validation
- Support section: complaint queue and refund decisions
- Admin section: analytics, user directory, event commands, customer event emails
- AI Assistant section: contextual chatbot

## Optional API Endpoints (available via FastAPI server)

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/forgot-password`
- `POST /api/auth/reset-password`
- `POST /api/ai/chat`
- `POST /api/notifications/event-detail-email`
- `GET /api/events`
- `POST /api/events`
- `PATCH /api/events/{event_id}/status`
- `GET /api/events/{event_id}/seats`
- `POST /api/bookings`
- `POST /api/bookings/{booking_id}/pay`
- `GET /api/bookings/{booking_id}`
- `GET /api/customers/{customer_id}/bookings`
- `POST /api/bookings/{booking_id}/refund-request`
- `POST /api/bookings/{booking_id}/refund-decision`
- `POST /api/tickets/validate`
- `POST /api/complaints`
- `PATCH /api/complaints/{complaint_id}`
- `GET /api/complaints`
- `GET /api/analytics`
- `GET /api/bookings/{booking_id}/ticket-download`
- `GET /api/bookings/{booking_id}/confirmation-email`

## Status Transition Notes

- Event: `draft -> published -> sold_out/completed` and cancellation allowed before completion.
- Booking: `pending_payment -> confirmed -> refund_requested -> refunded` or `pending_payment -> cancelled` on failed payment.
- Ticket: `issued -> used` or `issued -> invalidated` (refund/cancellation).
- Refund: `requested -> completed/rejected`.
- Support ticket: `open -> in_progress -> resolved/closed`.
>>>>>>> a9d392b (nitesh)
