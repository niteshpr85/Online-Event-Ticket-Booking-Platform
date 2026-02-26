from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import smtplib
from datetime import datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Booking,
    BookingSeat,
    BookingStatus,
    Event,
    EventStatus,
    Offer,
    OfferType,
    PasswordResetToken,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
    Seat,
    SupportStatus,
    SupportTicket,
    Ticket,
    TicketStatus,
    User,
    UserRole,
)
from app.schemas import BookingOut


def hash_password(password: str) -> str:
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    iterations = 200_000
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        scheme, iter_text, salt, expected = stored_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iter_text)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations).hex()
    return hmac.compare_digest(actual, expected)


def get_user_by_id(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def require_role(db: Session, user_id: int, role: UserRole) -> User:
    user = get_user_by_id(db, user_id)
    if user.role != role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User {user_id} must have role {role.value}",
        )
    return user


def register_user(
    db: Session,
    *,
    name: str,
    email: str,
    password: str,
    role: UserRole = UserRole.customer,
) -> User:
    allowed_roles = {UserRole.customer, UserRole.event_organizer, UserRole.platform_admin}
    if role not in allowed_roles:
        raise HTTPException(
            status_code=400,
            detail="Only customer, event organizer, or platform admin registration is allowed",
        )

    normalized_email = email.strip().lower()
    if not normalized_email:
        raise HTTPException(status_code=400, detail="Email is required")
    if db.scalar(select(User).where(User.email == normalized_email)):
        raise HTTPException(status_code=409, detail="Email is already registered")

    user = User(
        name=name.strip(),
        email=normalized_email,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.password_hash or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return user


def build_event_detail_email_content(db: Session, *, customer_id: int, event_id: int) -> tuple[User, str, str]:
    customer = get_user_by_id(db, customer_id)
    if customer.role != UserRole.customer:
        raise HTTPException(status_code=400, detail="Target user must be a customer")

    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    available_seats = (
        db.scalar(select(func.count()).select_from(Seat).where(Seat.event_id == event.id, Seat.is_available)) or 0
    )
    subject = f"Event Details: {event.title}"
    body = (
        f"Hi {customer.name},\n\n"
        f"Here are the event details:\n"
        f"- Event: {event.title}\n"
        f"- Description: {event.description}\n"
        f"- Venue: {event.venue}\n"
        f"- Start: {event.start_time.strftime('%Y-%m-%d %H:%M')}\n"
        f"- End: {event.end_time.strftime('%Y-%m-%d %H:%M')}\n"
        f"- Base Price: {float(event.base_price):.2f} {settings.currency}\n"
        f"- Status: {event.status.value}\n"
        f"- Seats Available: {int(available_seats)}\n\n"
        f"Thanks,\n{settings.app_name}"
    )
    return customer, subject, body


def send_email_notification(*, to_email: str, subject: str, body: str) -> dict:
    # If SMTP is not configured, keep the platform operational with simulation mode.
    if not settings.smtp_host:
        return {
            "sent": False,
            "mode": "simulation",
            "to_email": to_email,
            "subject": subject,
            "body": body,
        }

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    try:
        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_username and settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username and settings.smtp_password:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(message)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Email send failed: {exc}") from exc

    return {
        "sent": True,
        "mode": "smtp",
        "to_email": to_email,
        "subject": subject,
        "body": body,
    }


def _hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def request_password_reset(db: Session, *, email: str) -> dict:
    normalized_email = email.strip().lower()
    generic_msg = "If the account exists, password reset instructions were sent."
    user = db.scalar(select(User).where(User.email == normalized_email, User.is_active.is_(True)))
    if not user:
        return {
            "sent": True,
            "mode": "simulation",
            "message": generic_msg,
            "reset_token": None,
        }

    active_tokens = db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used.is_(False),
        )
    ).scalars().all()
    for token_row in active_tokens:
        token_row.used = True

    raw_token = secrets.token_urlsafe(32)
    token_row = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_reset_token(raw_token),
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        used=False,
    )
    db.add(token_row)
    db.commit()

    subject = f"{settings.app_name} password reset"
    body = (
        f"Hi {user.name},\n\n"
        f"We received a password reset request for your account.\n"
        f"Reset token (valid for 30 minutes): {raw_token}\n\n"
        "If you did not request this, you can ignore this email."
    )
    email_result = send_email_notification(to_email=user.email, subject=subject, body=body)
    return {
        "sent": True,
        "mode": email_result["mode"],
        "message": generic_msg,
        "reset_token": raw_token if email_result["mode"] == "simulation" else None,
    }


def reset_password_with_token(db: Session, *, token: str, new_password: str) -> dict:
    token_hash = _hash_reset_token(token.strip())
    token_row = db.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == token_hash, PasswordResetToken.used.is_(False))
        .order_by(PasswordResetToken.created_at.desc())
    )
    if not token_row:
        raise HTTPException(status_code=400, detail="Invalid or already used token")
    if token_row.expires_at < datetime.utcnow():
        token_row.used = True
        db.commit()
        raise HTTPException(status_code=400, detail="Reset token has expired")

    user = db.get(User, token_row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="Account is not active")

    user.password_hash = hash_password(new_password)
    token_row.used = True

    # Revoke any other outstanding reset tokens for the same account.
    remaining_tokens = db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used.is_(False),
            PasswordResetToken.id != token_row.id,
        )
    ).scalars().all()
    for row in remaining_tokens:
        row.used = True

    db.commit()
    return {"success": True, "message": "Password has been reset successfully"}


def send_event_detail_email(db: Session, *, customer_id: int, event_id: int) -> dict:
    customer, subject, body = build_event_detail_email_content(db, customer_id=customer_id, event_id=event_id)
    return send_email_notification(to_email=customer.email, subject=subject, body=body)


def compute_tax(amount: Decimal) -> Decimal:
    return (amount * Decimal(str(settings.tax_rate))).quantize(Decimal("0.01"))


def _release_booking_seats(booking: Booking) -> None:
    for bs in booking.booking_seats:
        bs.seat.is_available = True


def _set_event_sold_out_if_needed(db: Session, event: Event) -> None:
    remaining = db.scalar(select(func.count()).select_from(Seat).where(Seat.event_id == event.id, Seat.is_available))
    if remaining == 0 and event.status == EventStatus.published:
        event.status = EventStatus.sold_out
    if remaining and event.status == EventStatus.sold_out:
        event.status = EventStatus.published


def list_events_with_inventory(db: Session) -> list[dict]:
    stmt = (
        select(
            Event,
            func.count(Seat.id).label("total"),
            func.sum(case((Seat.is_available, 1), else_=0)).label("available"),
        )
        .outerjoin(Seat, Seat.event_id == Event.id)
        .group_by(Event.id)
        .order_by(Event.start_time.asc())
    )
    rows = db.execute(stmt).all()
    results: list[dict] = []
    for event, total, available in rows:
        results.append(
            {
                "id": event.id,
                "title": event.title,
                "description": event.description,
                "venue": event.venue,
                "start_time": event.start_time,
                "end_time": event.end_time,
                "base_price": float(event.base_price),
                "status": event.status,
                "organizer_id": event.organizer_id,
                "total_seats": int(total or 0),
                "available_seats": int(available or 0),
            }
        )
    return results


def create_event(
    db: Session,
    *,
    organizer_id: int,
    title: str,
    description: str,
    venue: str,
    start_time: datetime,
    end_time: datetime,
    base_price: float,
    row_count: int,
    seats_per_row: int,
) -> Event:
    require_role(db, organizer_id, UserRole.event_organizer)
    if end_time <= start_time:
        raise HTTPException(status_code=400, detail="end_time must be after start_time")

    event = Event(
        organizer_id=organizer_id,
        title=title,
        description=description,
        venue=venue,
        start_time=start_time,
        end_time=end_time,
        base_price=base_price,
        status=EventStatus.draft,
    )
    db.add(event)
    db.flush()

    for row_index in range(row_count):
        row_label = chr(ord("A") + row_index)
        for seat_num in range(1, seats_per_row + 1):
            db.add(Seat(event_id=event.id, row_label=row_label, seat_number=seat_num, is_available=True))

    db.commit()
    db.refresh(event)
    return event


def update_event_status(db: Session, event_id: int, new_status: EventStatus) -> Event:
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    allowed = {
        EventStatus.draft: {EventStatus.published, EventStatus.cancelled},
        EventStatus.published: {EventStatus.sold_out, EventStatus.cancelled, EventStatus.completed},
        EventStatus.sold_out: {EventStatus.published, EventStatus.cancelled, EventStatus.completed},
        EventStatus.cancelled: set(),
        EventStatus.completed: set(),
    }
    if new_status not in allowed[event.status] and new_status != event.status:
        raise HTTPException(status_code=400, detail=f"Invalid event status transition: {event.status} -> {new_status}")

    event.status = new_status
    if new_status == EventStatus.cancelled:
        for booking in event.bookings:
            if booking.status in {BookingStatus.pending_payment, BookingStatus.confirmed, BookingStatus.refund_requested}:
                booking.status = BookingStatus.refunded
                _release_booking_seats(booking)
                if booking.payment:
                    booking.payment.status = PaymentStatus.refunded
                for link in booking.booking_seats:
                    if link.ticket:
                        link.ticket.status = TicketStatus.invalidated
    db.commit()
    db.refresh(event)
    return event


def _apply_offer(db: Session, subtotal: Decimal, offer_code: str | None) -> tuple[Decimal, str | None]:
    if not offer_code:
        return Decimal("0.00"), None

    offer = db.scalar(select(Offer).where(Offer.code == offer_code.upper()))
    if not offer or not offer.active:
        raise HTTPException(status_code=400, detail="Invalid or inactive offer code")
    if offer.valid_until and offer.valid_until < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Offer has expired")
    if offer.usage_limit is not None and offer.used_count >= offer.usage_limit:
        raise HTTPException(status_code=400, detail="Offer usage limit reached")

    if offer.offer_type == OfferType.percentage:
        discount = (subtotal * Decimal(str(offer.value / 100))).quantize(Decimal("0.01"))
    else:
        discount = Decimal(str(offer.value)).quantize(Decimal("0.01"))

    if discount > subtotal:
        discount = subtotal

    offer.used_count += 1
    return discount, offer.code


def create_booking(
    db: Session,
    *,
    customer_id: int,
    event_id: int,
    seat_ids: list[int],
    offer_code: str | None = None,
) -> Booking:
    require_role(db, customer_id, UserRole.customer)
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event.status not in {EventStatus.published, EventStatus.sold_out}:
        raise HTTPException(status_code=400, detail="Event is not available for booking")
    if event.start_time <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Cannot book tickets for past events")

    seat_rows = db.execute(select(Seat).where(Seat.id.in_(seat_ids), Seat.event_id == event_id)).scalars().all()
    if len(seat_rows) != len(set(seat_ids)):
        raise HTTPException(status_code=400, detail="One or more seats are invalid for this event")
    unavailable = [seat.id for seat in seat_rows if not seat.is_available]
    if unavailable:
        raise HTTPException(status_code=409, detail=f"Seats unavailable: {unavailable}")

    subtotal = Decimal("0.00")
    seat_prices: dict[int, Decimal] = {}
    for seat in seat_rows:
        price = Decimal(str(seat.price_override if seat.price_override is not None else event.base_price))
        subtotal += price
        seat_prices[seat.id] = price

    discount_amount, canonical_offer_code = _apply_offer(db, subtotal, offer_code)
    taxable = subtotal - discount_amount
    tax_amount = compute_tax(taxable)
    total_amount = taxable + tax_amount

    booking = Booking(
        customer_id=customer_id,
        event_id=event_id,
        status=BookingStatus.pending_payment,
        subtotal=subtotal,
        discount_amount=discount_amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
        offer_code=canonical_offer_code,
    )
    db.add(booking)
    db.flush()

    for seat in seat_rows:
        seat.is_available = False
        db.add(BookingSeat(booking_id=booking.id, seat_id=seat.id, ticket_price=seat_prices[seat.id]))

    payment = Payment(
        booking_id=booking.id,
        amount=total_amount,
        status=PaymentStatus.initiated,
        method="pending",
        transaction_ref=f"TXN-{uuid4().hex[:12].upper()}",
    )
    db.add(payment)
    _set_event_sold_out_if_needed(db, event)
    db.commit()
    db.refresh(booking)
    return booking


def capture_payment(
    db: Session,
    *,
    booking_id: int,
    customer_id: int,
    method: str,
    mark_success: bool,
) -> Booking:
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.customer_id != customer_id:
        raise HTTPException(status_code=403, detail="Booking does not belong to customer")
    if booking.status != BookingStatus.pending_payment:
        raise HTTPException(status_code=400, detail="Payment can only be captured for pending bookings")
    if not booking.payment:
        raise HTTPException(status_code=500, detail="Booking payment record missing")

    booking.payment.method = method
    if mark_success:
        booking.payment.status = PaymentStatus.paid
        booking.payment.paid_at = datetime.utcnow()
        booking.status = BookingStatus.confirmed
        for link in booking.booking_seats:
            db.add(Ticket(booking_seat_id=link.id, qr_code=f"TKT-{uuid4().hex[:16].upper()}"))
    else:
        booking.payment.status = PaymentStatus.failed
        booking.status = BookingStatus.cancelled
        _release_booking_seats(booking)

    _set_event_sold_out_if_needed(db, booking.event)
    db.commit()
    db.refresh(booking)
    return booking


def request_refund(db: Session, *, booking_id: int, customer_id: int, reason: str) -> Refund:
    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.customer_id != customer_id:
        raise HTTPException(status_code=403, detail="Booking does not belong to customer")
    if booking.status != BookingStatus.confirmed:
        raise HTTPException(status_code=400, detail="Refund can only be requested for confirmed bookings")
    if booking.refund:
        raise HTTPException(status_code=400, detail="Refund already exists for this booking")

    refund = Refund(
        booking_id=booking.id,
        status=RefundStatus.requested,
        reason=reason,
        refund_amount=booking.total_amount,
        requested_by=customer_id,
    )
    booking.status = BookingStatus.refund_requested
    db.add(refund)
    db.commit()
    db.refresh(refund)
    return refund


def decide_refund(db: Session, *, booking_id: int, support_executive_id: int, approve: bool) -> Refund:
    require_role(db, support_executive_id, UserRole.support_executive)
    booking = db.get(Booking, booking_id)
    if not booking or not booking.refund:
        raise HTTPException(status_code=404, detail="Refund request not found")
    refund = booking.refund
    if refund.status != RefundStatus.requested:
        raise HTTPException(status_code=400, detail="Refund is already resolved")

    refund.resolved_by = support_executive_id
    refund.resolved_at = datetime.utcnow()
    if approve:
        refund.status = RefundStatus.completed
        booking.status = BookingStatus.refunded
        if booking.payment:
            booking.payment.status = PaymentStatus.refunded
        for link in booking.booking_seats:
            link.seat.is_available = True
            if link.ticket:
                link.ticket.status = TicketStatus.invalidated
        _set_event_sold_out_if_needed(db, booking.event)
    else:
        refund.status = RefundStatus.rejected
        booking.status = BookingStatus.confirmed

    db.commit()
    db.refresh(refund)
    return refund


def validate_ticket(db: Session, *, qr_code: str, entry_manager_id: int) -> tuple[bool, str, Ticket | None]:
    require_role(db, entry_manager_id, UserRole.entry_manager)
    ticket = db.scalar(select(Ticket).where(Ticket.qr_code == qr_code))
    if not ticket:
        return False, "Ticket not found", None
    if ticket.status == TicketStatus.used:
        return False, "Ticket already used", ticket
    if ticket.status != TicketStatus.issued:
        return False, "Ticket is not valid for entry", ticket

    booking = ticket.booking_seat.booking
    if booking.status != BookingStatus.confirmed:
        return False, "Booking is not active", ticket
    event = booking.event
    if event.status == EventStatus.cancelled:
        return False, "Event is cancelled", ticket

    ticket.status = TicketStatus.used
    ticket.entry_manager_id = entry_manager_id
    ticket.validated_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)
    return True, "Ticket validated", ticket


def create_complaint(
    db: Session,
    *,
    customer_id: int,
    booking_id: int | None,
    event_id: int | None,
    subject: str,
    description: str,
) -> SupportTicket:
    require_role(db, customer_id, UserRole.customer)
    if booking_id:
        booking = db.get(Booking, booking_id)
        if not booking or booking.customer_id != customer_id:
            raise HTTPException(status_code=400, detail="Invalid booking for complaint")
    if event_id and not db.get(Event, event_id):
        raise HTTPException(status_code=400, detail="Invalid event for complaint")

    ticket = SupportTicket(
        customer_id=customer_id,
        booking_id=booking_id,
        event_id=event_id,
        subject=subject,
        description=description,
        status=SupportStatus.open,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def update_complaint(
    db: Session,
    *,
    complaint_id: int,
    support_executive_id: int,
    new_status: SupportStatus,
    resolution: str | None,
) -> SupportTicket:
    require_role(db, support_executive_id, UserRole.support_executive)
    complaint = db.get(SupportTicket, complaint_id)
    if not complaint:
        raise HTTPException(status_code=404, detail="Complaint not found")

    complaint.assigned_to = support_executive_id
    complaint.status = new_status
    if resolution:
        complaint.resolution = resolution
    db.commit()
    db.refresh(complaint)
    return complaint


def booking_to_out(booking: Booking) -> BookingOut:
    ticket_codes = [link.ticket.qr_code for link in booking.booking_seats if link.ticket]
    return BookingOut(
        id=booking.id,
        customer_id=booking.customer_id,
        event_id=booking.event_id,
        status=booking.status,
        subtotal=float(booking.subtotal),
        discount_amount=float(booking.discount_amount),
        tax_amount=float(booking.tax_amount),
        total_amount=float(booking.total_amount),
        offer_code=booking.offer_code,
        ticket_codes=ticket_codes,
        payment_status=booking.payment.status if booking.payment else None,
        refund_status=booking.refund.status if booking.refund else None,
    )


def seed_initial_data(db: Session) -> None:
    has_users = db.scalar(select(func.count()).select_from(User))
    if has_users:
        existing_users = db.execute(select(User)).scalars().all()
        default_passwords = {
            "admin@ticket.local": "admin123",
            "organizer@ticket.local": "organizer123",
            "customer@ticket.local": "customer123",
            "entry@ticket.local": "entry123",
            "support@ticket.local": "support123",
        }
        changed = False
        for user in existing_users:
            if not user.password_hash:
                user.password_hash = hash_password(default_passwords.get(user.email, "changeme123"))
                changed = True
        if changed:
            db.commit()
        return

    users = [
        User(
            name="Admin One",
            email="admin@ticket.local",
            password_hash=hash_password("admin123"),
            role=UserRole.platform_admin,
        ),
        User(
            name="Organizer One",
            email="organizer@ticket.local",
            password_hash=hash_password("organizer123"),
            role=UserRole.event_organizer,
        ),
        User(
            name="Customer One",
            email="customer@ticket.local",
            password_hash=hash_password("customer123"),
            role=UserRole.customer,
        ),
        User(
            name="Entry Manager One",
            email="entry@ticket.local",
            password_hash=hash_password("entry123"),
            role=UserRole.entry_manager,
        ),
        User(
            name="Support One",
            email="support@ticket.local",
            password_hash=hash_password("support123"),
            role=UserRole.support_executive,
        ),
    ]
    db.add_all(users)
    db.flush()

    offers = [
        Offer(code="WELCOME10", offer_type=OfferType.percentage, value=10, active=True, usage_limit=100),
        Offer(code="FLAT5", offer_type=OfferType.fixed, value=5, active=True, usage_limit=None),
    ]
    db.add_all(offers)
    db.flush()

    event = Event(
        title="Indie Music Night",
        description="A live showcase with three local indie bands.",
        venue="City Hall Stage",
        start_time=datetime.utcnow() + timedelta(days=5),
        end_time=datetime.utcnow() + timedelta(days=5, hours=4),
        base_price=35,
        status=EventStatus.published,
        organizer_id=users[1].id,
    )
    db.add(event)
    db.flush()

    for row_label in ["A", "B", "C", "D"]:
        for seat_num in range(1, 11):
            db.add(Seat(event_id=event.id, row_label=row_label, seat_number=seat_num, is_available=True))

    db.commit()
