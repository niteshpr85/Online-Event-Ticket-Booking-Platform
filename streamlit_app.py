from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai_chat import get_ai_chat_response
from app.db import Base, SessionLocal, engine
from app.migrations import run_migrations
from app.models import (
    Booking,
    BookingSeat,
    BookingStatus,
    Event,
    EventStatus,
    Seat,
    SupportStatus,
    SupportTicket,
    User,
    UserRole,
)
from app.services import (
    authenticate_user,
    booking_to_out,
    capture_payment,
    create_booking,
    create_complaint,
    create_event,
    decide_refund,
    list_events_with_inventory,
    register_user,
    request_password_reset,
    request_refund,
    reset_password_with_token,
    seed_initial_data,
    send_event_detail_email,
    update_complaint,
    update_event_status,
    validate_ticket,
)


@st.cache_resource(show_spinner=False)
def init_database() -> bool:
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    db = SessionLocal()
    try:
        seed_initial_data(db)
    finally:
        db.close()
    return True


@contextmanager
def db_session() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def show_error(exc: Exception) -> None:
    detail = getattr(exc, "detail", None)
    st.error(detail if detail else str(exc))


def load_events() -> list[dict]:
    with db_session() as db:
        rows = list_events_with_inventory(db)
    return [
        {
            **row,
            "status": row["status"].value,
            "start_time": row["start_time"].strftime("%Y-%m-%d %H:%M"),
            "end_time": row["end_time"].strftime("%Y-%m-%d %H:%M"),
        }
        for row in rows
    ]


def load_available_seats(event_id: int) -> list[dict]:
    with db_session() as db:
        seats = (
            db.execute(select(Seat).where(Seat.event_id == event_id, Seat.is_available.is_(True)).order_by(Seat.row_label, Seat.seat_number))
            .scalars()
            .all()
        )
    return [{"id": s.id, "label": f"{s.row_label}{s.seat_number}"} for s in seats]


def load_customer_bookings(customer_id: int) -> list[dict]:
    with db_session() as db:
        bookings = (
            db.execute(
                select(Booking)
                .where(Booking.customer_id == customer_id)
                .options(
                    selectinload(Booking.booking_seats).selectinload(BookingSeat.ticket),
                    selectinload(Booking.payment),
                    selectinload(Booking.refund),
                )
                .order_by(Booking.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [booking_to_out(b).model_dump() for b in bookings]


def load_users(role: UserRole | None = None) -> list[dict]:
    with db_session() as db:
        stmt = select(User).order_by(User.id)
        if role:
            stmt = stmt.where(User.role == role)
        users = db.execute(stmt).scalars().all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role.value} for u in users]


def load_complaints() -> list[dict]:
    with db_session() as db:
        rows = db.execute(select(SupportTicket).order_by(SupportTicket.created_at.desc())).scalars().all()
    return [
        {
            "id": c.id,
            "customer_id": c.customer_id,
            "booking_id": c.booking_id,
            "event_id": c.event_id,
            "subject": c.subject,
            "description": c.description,
            "status": c.status.value,
            "assigned_to": c.assigned_to,
            "resolution": c.resolution,
            "created_at": c.created_at,
        }
        for c in rows
    ]


def load_analytics() -> dict:
    with db_session() as db:
        bookings = db.execute(select(Booking)).scalars().all()
        events = db.execute(select(Event)).scalars().all()
        users = db.execute(select(User)).scalars().all()
    confirmed = sum(1 for b in bookings if b.status == BookingStatus.confirmed)
    refunded = sum(1 for b in bookings if b.status == BookingStatus.refunded)
    gross = sum(float(b.total_amount) for b in bookings if b.status in {BookingStatus.confirmed, BookingStatus.refund_requested})
    return {
        "total_users": len(users),
        "total_events": len(events),
        "total_bookings": len(bookings),
        "confirmed_bookings": confirmed,
        "refunded_bookings": refunded,
        "gross_sales": round(gross, 2),
    }


def auth_screen() -> None:
    st.title("Online Event Ticket Booking Platform")
    st.caption("Login to continue")
    tabs = st.tabs(["Login", "Register", "Forgot Password"])

    with tabs[0]:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")
        if submit:
            try:
                with db_session() as db:
                    user = authenticate_user(db, email=email, password=password)
                st.session_state["auth_user"] = {
                    "id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "role": user.role.value,
                }
                st.rerun()
            except Exception as exc:
                show_error(exc)

    with tabs[1]:
        with st.form("register_form"):
            name = st.text_input("Name")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            confirm = st.text_input("Confirm Password", type="password")
            role = st.selectbox(
                "Role",
                options=[UserRole.customer.value, UserRole.event_organizer.value, UserRole.platform_admin.value],
            )
            submit = st.form_submit_button("Create Account")
        if submit:
            if password != confirm:
                st.error("Passwords do not match")
            else:
                try:
                    with db_session() as db:
                        user = register_user(db, name=name, email=email, password=password, role=UserRole(role))
                    st.success(f"Account created for {user.email}. Please login.")
                except Exception as exc:
                    show_error(exc)

    with tabs[2]:
        with st.form("forgot_form"):
            email = st.text_input("Registered Email")
            submit_forgot = st.form_submit_button("Send Reset Instructions")
        if submit_forgot:
            try:
                with db_session() as db:
                    result = request_password_reset(db, email=email)
                st.success(result["message"])
                if result.get("reset_token"):
                    st.info("SMTP not configured. Use this token to reset password:")
                    st.code(result["reset_token"])
            except Exception as exc:
                show_error(exc)

        with st.form("reset_form"):
            token = st.text_input("Reset Token")
            new_password = st.text_input("New Password", type="password")
            confirm = st.text_input("Confirm New Password", type="password")
            submit_reset = st.form_submit_button("Reset Password")
        if submit_reset:
            if new_password != confirm:
                st.error("Passwords do not match")
            else:
                try:
                    with db_session() as db:
                        result = reset_password_with_token(db, token=token, new_password=new_password)
                    st.success(result["message"])
                except Exception as exc:
                    show_error(exc)


def render_home(user: dict) -> None:
    st.header("Home")
    st.write(f"Welcome, **{user['name']}**")
    st.write(f"Role: `{user['role']}`")
    st.write("Use the sidebar to open one section at a time.")


def render_book_tickets(user_id: int) -> None:
    st.header("Book Tickets")
    events = load_events()
    if not events:
        st.info("No events available.")
        return
    st.dataframe(events, use_container_width=True)

    options = {f"{e['id']} - {e['title']} ({e['available_seats']} seats)": e["id"] for e in events}
    selected_label = st.selectbox("Select Event", options=list(options.keys()))
    event_id = options[selected_label]

    seats = load_available_seats(event_id)
    seat_map = {s["id"]: s["label"] for s in seats}
    selected_seat_ids = st.multiselect(
        "Select Seats",
        options=list(seat_map.keys()),
        format_func=lambda sid: f"{sid} ({seat_map[sid]})",
    )
    offer_code = st.text_input("Offer Code (optional)")

    if st.button("Create Booking", type="primary"):
        if not selected_seat_ids:
            st.warning("Select at least one seat.")
            return
        try:
            with db_session() as db:
                booking = create_booking(
                    db,
                    customer_id=user_id,
                    event_id=int(event_id),
                    seat_ids=[int(i) for i in selected_seat_ids],
                    offer_code=offer_code.strip() or None,
                )
                payload = booking_to_out(booking).model_dump()
                booking_id = booking.id
            st.session_state["last_booking_id"] = booking_id
            if payload.get("ticket_codes"):
                st.session_state["last_ticket_code"] = payload["ticket_codes"][0]
            st.success(f"Booking #{booking_id} created")
            st.json(payload)
        except Exception as exc:
            show_error(exc)


def render_payments(user_id: int) -> None:
    st.header("Payments")
    bookings = load_customer_bookings(user_id)
    st.dataframe(bookings, use_container_width=True)
    pending = [b for b in bookings if b["status"] == BookingStatus.pending_payment.value]
    if not pending:
        st.info("No pending payments.")
        return
    booking_map = {f"{b['id']} | total={b['total_amount']}": int(b["id"]) for b in pending}
    selected = st.selectbox("Pending Booking", options=list(booking_map.keys()))
    booking_id = booking_map[selected]
    method = st.text_input("Method", value="upi")
    success = st.toggle("Mark payment as success", value=True)
    if st.button("Capture Payment"):
        try:
            with db_session() as db:
                booking = capture_payment(
                    db,
                    booking_id=booking_id,
                    customer_id=user_id,
                    method=method.strip() or "card",
                    mark_success=success,
                )
                payload = booking_to_out(booking).model_dump()
            st.success("Payment processed")
            st.json(payload)
        except Exception as exc:
            show_error(exc)


def render_refunds(user_id: int) -> None:
    st.header("Refunds")
    bookings = load_customer_bookings(user_id)
    st.dataframe(bookings, use_container_width=True)
    eligible = [b for b in bookings if b["status"] == BookingStatus.confirmed.value]
    if not eligible:
        st.info("No confirmed bookings available for refund request.")
        return
    booking_map = {f"{b['id']} | total={b['total_amount']}": int(b["id"]) for b in eligible}
    selected = st.selectbox("Confirmed Booking", options=list(booking_map.keys()))
    reason = st.text_input("Reason", value="Unable to attend")
    if st.button("Request Refund"):
        try:
            with db_session() as db:
                refund = request_refund(db, booking_id=booking_map[selected], customer_id=user_id, reason=reason.strip())
            st.success(f"Refund requested (id={refund.id})")
            st.json({"refund_id": refund.id, "status": refund.status.value, "amount": float(refund.refund_amount)})
        except Exception as exc:
            show_error(exc)


def render_customer_complaints(user_id: int) -> None:
    st.header("Complaints")
    with st.form("complaint_form"):
        booking_id = st.number_input("Booking ID (optional)", min_value=0, value=0, step=1)
        event_id = st.number_input("Event ID (optional)", min_value=0, value=0, step=1)
        subject = st.text_input("Subject", value="Need help")
        description = st.text_area("Description", value="Please assist with my booking.")
        submit = st.form_submit_button("Submit Complaint")
    if submit:
        try:
            with db_session() as db:
                ticket = create_complaint(
                    db,
                    customer_id=user_id,
                    booking_id=int(booking_id) if booking_id > 0 else None,
                    event_id=int(event_id) if event_id > 0 else None,
                    subject=subject.strip(),
                    description=description.strip(),
                )
            st.success(f"Complaint #{ticket.id} created")
        except Exception as exc:
            show_error(exc)

    all_tickets = [c for c in load_complaints() if int(c["customer_id"]) == user_id]
    st.subheader("My Complaints")
    st.dataframe(all_tickets, use_container_width=True)


def render_event_email(user_id: int) -> None:
    st.header("Event Email")
    events = load_events()
    if not events:
        st.info("No events available.")
        return
    event_map = {f"{e['id']} - {e['title']}": int(e["id"]) for e in events}
    selected = st.selectbox("Event", options=list(event_map.keys()))
    if st.button("Send Event Details to My Email"):
        try:
            with db_session() as db:
                result = send_event_detail_email(db, customer_id=user_id, event_id=event_map[selected])
            if result["sent"]:
                st.success(f"Email sent to {result['to_email']}")
            else:
                st.info("SMTP not configured, showing simulated email:")
            st.json(result)
        except Exception as exc:
            show_error(exc)


def render_organizer(user_id: int) -> None:
    st.header("Organizer")
    with st.form("create_event_form"):
        title = st.text_input("Title", value="Acoustic Friday")
        description = st.text_area("Description", value="Weekly acoustic live session")
        venue = st.text_input("Venue", value="Open Air Arena")
        start_date = st.date_input("Start Date", value=date.today() + timedelta(days=7))
        start_time = st.time_input("Start Time", value=time(hour=18, minute=0))
        end_date = st.date_input("End Date", value=date.today() + timedelta(days=7))
        end_time = st.time_input("End Time", value=time(hour=21, minute=0))
        base_price = st.number_input("Base Price", min_value=1.0, value=30.0, step=1.0)
        row_count = st.number_input("Rows", min_value=1, max_value=26, value=4, step=1)
        seats_per_row = st.number_input("Seats Per Row", min_value=1, max_value=50, value=10, step=1)
        submit = st.form_submit_button("Create Event")
    if submit:
        try:
            with db_session() as db:
                event = create_event(
                    db,
                    organizer_id=user_id,
                    title=title.strip(),
                    description=description.strip(),
                    venue=venue.strip(),
                    start_time=datetime.combine(start_date, start_time),
                    end_time=datetime.combine(end_date, end_time),
                    base_price=float(base_price),
                    row_count=int(row_count),
                    seats_per_row=int(seats_per_row),
                )
            st.success(f"Event #{event.id} created")
        except Exception as exc:
            show_error(exc)

    st.subheader("My Events")
    events = [e for e in load_events() if int(e["organizer_id"]) == user_id]
    st.dataframe(events, use_container_width=True)
    if events:
        status_map = {f"{e['id']} - {e['title']} ({e['status']})": int(e["id"]) for e in events}
        selected = st.selectbox("Event", options=list(status_map.keys()))
        new_status = st.selectbox("New Status", options=[s.value for s in EventStatus])
        if st.button("Update Status"):
            try:
                with db_session() as db:
                    update_event_status(db, event_id=status_map[selected], new_status=EventStatus(new_status))
                st.success("Status updated")
            except Exception as exc:
                show_error(exc)


def render_create_event(user_id: int, role: str) -> None:
    st.header("Create Event")
    organizer_id = user_id
    if role == UserRole.platform_admin.value:
        organizer_users = load_users(UserRole.event_organizer)
        if not organizer_users:
            st.warning("No organizer accounts found. Register an event organizer first.")
            return
        organizer_map = {f"{u['id']} - {u['name']} ({u['email']})": int(u["id"]) for u in organizer_users}
        selected = st.selectbox("Create event under organizer", options=list(organizer_map.keys()))
        organizer_id = organizer_map[selected]
        st.info("Admin creates the event on behalf of selected organizer.")

    with st.form("create_event_simple_form"):
        title = st.text_input("Title", value="Weekend Live Show")
        description = st.text_area("Description", value="Live event description")
        venue = st.text_input("Venue", value="City Auditorium")
        start_date = st.date_input("Start Date", value=date.today() + timedelta(days=7), key="create_start_date")
        start_time = st.time_input("Start Time", value=time(hour=18, minute=0), key="create_start_time")
        end_date = st.date_input("End Date", value=date.today() + timedelta(days=7), key="create_end_date")
        end_time = st.time_input("End Time", value=time(hour=21, minute=0), key="create_end_time")
        base_price = st.number_input("Base Price", min_value=1.0, value=30.0, step=1.0, key="create_base_price")
        row_count = st.number_input("Rows", min_value=1, max_value=26, value=4, step=1, key="create_row_count")
        seats_per_row = st.number_input(
            "Seats Per Row",
            min_value=1,
            max_value=50,
            value=10,
            step=1,
            key="create_seats_per_row",
        )
        submit = st.form_submit_button("Create Event")
    if submit:
        try:
            with db_session() as db:
                event = create_event(
                    db,
                    organizer_id=int(organizer_id),
                    title=title.strip(),
                    description=description.strip(),
                    venue=venue.strip(),
                    start_time=datetime.combine(start_date, start_time),
                    end_time=datetime.combine(end_date, end_time),
                    base_price=float(base_price),
                    row_count=int(row_count),
                    seats_per_row=int(seats_per_row),
                )
            st.success(f"Event #{event.id} created")
        except Exception as exc:
            show_error(exc)


def render_entry(user_id: int) -> None:
    st.header("Entry Validation")
    qr_code = st.text_input("Ticket QR Code", value=str(st.session_state.get("last_ticket_code", "")))
    if st.button("Validate Ticket"):
        try:
            with db_session() as db:
                valid, message, ticket = validate_ticket(db, qr_code=qr_code.strip(), entry_manager_id=user_id)
            if valid:
                st.success(message)
            else:
                st.warning(message)
            st.json({"valid": valid, "message": message, "ticket_status": ticket.status.value if ticket else None})
        except Exception as exc:
            show_error(exc)


def render_support(user_id: int) -> None:
    st.header("Support Desk")
    complaints = load_complaints()
    st.subheader("Complaints Queue")
    st.dataframe(complaints, use_container_width=True)

    with st.form("update_complaint_form"):
        complaint_id = st.number_input("Complaint ID", min_value=1, value=1, step=1)
        status = st.selectbox("Status", options=[s.value for s in SupportStatus if s != SupportStatus.open])
        resolution = st.text_area("Resolution", value="Issue resolved and customer informed.")
        submit = st.form_submit_button("Update Complaint")
    if submit:
        try:
            with db_session() as db:
                c = update_complaint(
                    db,
                    complaint_id=int(complaint_id),
                    support_executive_id=user_id,
                    new_status=SupportStatus(status),
                    resolution=resolution.strip() or None,
                )
            st.success(f"Complaint #{c.id} updated")
        except Exception as exc:
            show_error(exc)

    with st.form("refund_decision_form"):
        booking_id = st.number_input("Booking ID", min_value=1, value=1, step=1)
        approve = st.toggle("Approve Refund", value=True)
        submit_refund = st.form_submit_button("Process Refund Decision")
    if submit_refund:
        try:
            with db_session() as db:
                refund = decide_refund(db, booking_id=int(booking_id), support_executive_id=user_id, approve=approve)
            st.success(f"Refund #{refund.id} processed ({refund.status.value})")
        except Exception as exc:
            show_error(exc)


def render_admin() -> None:
    st.header("Admin Center")
    stats = load_analytics()
    cols = st.columns(6)
    cols[0].metric("Users", stats["total_users"])
    cols[1].metric("Events", stats["total_events"])
    cols[2].metric("Bookings", stats["total_bookings"])
    cols[3].metric("Confirmed", stats["confirmed_bookings"])
    cols[4].metric("Refunded", stats["refunded_bookings"])
    cols[5].metric("Gross Sales", f"${stats['gross_sales']:.2f}")

    st.subheader("Users")
    role_filter = st.selectbox("Filter", options=["all"] + [r.value for r in UserRole])
    users = load_users(None if role_filter == "all" else UserRole(role_filter))
    st.dataframe(users, use_container_width=True)

    st.subheader("Event Status Command")
    events = load_events()
    st.dataframe(events, use_container_width=True)
    if events:
        event_map = {f"{e['id']} - {e['title']} ({e['status']})": int(e["id"]) for e in events}
        selected_event = st.selectbox("Event", options=list(event_map.keys()))
        next_status = st.selectbox("Set Status", options=[s.value for s in EventStatus], key="admin_event_status")
        if st.button("Apply Event Status"):
            try:
                with db_session() as db:
                    update_event_status(db, event_id=event_map[selected_event], new_status=EventStatus(next_status))
                st.success("Event status updated")
            except Exception as exc:
                show_error(exc)

    st.subheader("Send Event Detail Email")
    customers = load_users(UserRole.customer)
    if events and customers:
        event_map = {f"{e['id']} - {e['title']}": int(e["id"]) for e in events}
        customer_map = {f"{c['id']} - {c['name']} ({c['email']})": int(c["id"]) for c in customers}
        selected_event = st.selectbox("Email Event", options=list(event_map.keys()), key="admin_email_event")
        selected_customer = st.selectbox("Email Customer", options=list(customer_map.keys()), key="admin_email_customer")
        if st.button("Send Event Email"):
            try:
                with db_session() as db:
                    result = send_event_detail_email(
                        db,
                        customer_id=customer_map[selected_customer],
                        event_id=event_map[selected_event],
                    )
                if result["sent"]:
                    st.success(f"Email sent to {result['to_email']}")
                else:
                    st.info("SMTP not configured, showing simulated email:")
                st.json(result)
            except Exception as exc:
                show_error(exc)


def render_ai_assistant(user_id: int, role: str) -> None:
    st.header("AI Assistant")
    st.caption("Ask about booking, payments, refunds, complaints, events, and admin operations.")
    if os.getenv("OPENAI_API_KEY"):
        st.success(f"Mode: OpenAI ({os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')})")
    else:
        st.info("Mode: Fallback assistant (set OPENAI_API_KEY for OpenAI mode)")

    if st.button("Clear Chat"):
        st.session_state["chat_history"] = []
        st.rerun()

    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    prompt = st.chat_input("Ask your question...")
    if prompt:
        st.session_state["chat_history"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
        with db_session() as db:
            result = get_ai_chat_response(db, user_id=user_id, user_role=role, message=prompt)
        reply = f"{result['answer']}\n\n_Mode: {result['mode']}_"
        st.session_state["chat_history"].append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.write(reply)


def main() -> None:
    st.set_page_config(page_title="Online Event Ticket Booking Platform", layout="wide")
    init_database()

    if "auth_user" not in st.session_state:
        st.session_state["auth_user"] = None
    if "last_booking_id" not in st.session_state:
        st.session_state["last_booking_id"] = 0
    if "last_ticket_code" not in st.session_state:
        st.session_state["last_ticket_code"] = ""
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    if st.session_state["auth_user"] is None:
        auth_screen()
        return

    user = st.session_state["auth_user"]
    user_id = int(user["id"])
    role = str(user["role"])

    with st.sidebar:
        st.write(f"User: {user['name']}")
        st.write(f"Role: `{role}`")
        if os.getenv("SMTP_HOST"):
            st.success("Email: SMTP enabled")
        else:
            st.warning("Email: simulation mode")
        if st.button("Logout"):
            st.session_state["auth_user"] = None
            st.session_state["chat_history"] = []
            st.rerun()

    sections = ["Home", "AI Assistant"]
    if role == UserRole.customer.value:
        sections = ["Home", "Book Tickets", "Payments", "Refunds", "Complaints", "Event Email", "AI Assistant"]
    elif role == UserRole.event_organizer.value:
        sections = ["Home", "Create Event", "Organizer", "AI Assistant"]
    elif role == UserRole.entry_manager.value:
        sections = ["Home", "Entry Validation", "AI Assistant"]
    elif role == UserRole.support_executive.value:
        sections = ["Home", "Support Desk", "AI Assistant"]
    elif role == UserRole.platform_admin.value:
        sections = ["Home", "Create Event", "Admin Center", "AI Assistant"]

    section = st.sidebar.radio("Section", options=sections)

    if section == "Home":
        render_home(user)
    elif section == "Book Tickets":
        render_book_tickets(user_id)
    elif section == "Payments":
        render_payments(user_id)
    elif section == "Refunds":
        render_refunds(user_id)
    elif section == "Complaints":
        render_customer_complaints(user_id)
    elif section == "Event Email":
        render_event_email(user_id)
    elif section == "Organizer":
        render_organizer(user_id)
    elif section == "Create Event":
        render_create_event(user_id, role)
    elif section == "Entry Validation":
        render_entry(user_id)
    elif section == "Support Desk":
        render_support(user_id)
    elif section == "Admin Center":
        render_admin()
    elif section == "AI Assistant":
        render_ai_assistant(user_id, role)


if __name__ == "__main__":
    main()
