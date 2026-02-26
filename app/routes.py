from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai_chat import get_ai_chat_response
from app.db import get_db
from app.models import Booking, BookingSeat, BookingStatus, Event, Offer, Seat, SupportTicket, User
from app.schemas import (
    AIChatRequest,
    AIChatResponse,
    BookingCreate,
    BookingOut,
    ComplaintCreate,
    ComplaintUpdate,
    EventDetailEmailRequest,
    EventDetailEmailResponse,
    EventCreate,
    EventOut,
    EventStatusUpdate,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    PaymentCapture,
    RegisterRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    RefundDecision,
    RefundRequestCreate,
    TicketValidation,
    TicketValidationOut,
    UserOut,
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
    send_event_detail_email,
    update_complaint,
    update_event_status,
    validate_ticket,
)


router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/api/users", response_model=list[UserOut])
def list_users(role: str | None = None, db: Session = Depends(get_db)) -> list[User]:
    stmt = select(User).order_by(User.id)
    if role:
        stmt = stmt.where(User.role == role)
    return db.execute(stmt).scalars().all()


@router.post("/api/notifications/event-detail-email", response_model=EventDetailEmailResponse)
def send_event_detail_email_endpoint(payload: EventDetailEmailRequest, db: Session = Depends(get_db)) -> dict:
    return send_event_detail_email(db, customer_id=payload.customer_id, event_id=payload.event_id)


@router.post("/api/auth/register", response_model=UserOut)
def register_endpoint(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    return register_user(
        db,
        name=payload.name,
        email=payload.email,
        password=payload.password,
        role=payload.role,
    )


@router.post("/api/auth/login", response_model=UserOut)
def login_endpoint(payload: LoginRequest, db: Session = Depends(get_db)) -> User:
    return authenticate_user(db, email=payload.email, password=payload.password)


@router.post("/api/auth/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password_endpoint(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    return request_password_reset(db, email=payload.email)


@router.post("/api/auth/reset-password", response_model=ResetPasswordResponse)
def reset_password_endpoint(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> dict:
    return reset_password_with_token(db, token=payload.token, new_password=payload.new_password)


@router.post("/api/ai/chat", response_model=AIChatResponse)
def ai_chat_endpoint(payload: AIChatRequest, db: Session = Depends(get_db)) -> dict:
    return get_ai_chat_response(
        db,
        user_id=payload.user_id,
        user_role=payload.user_role.value,
        message=payload.message,
    )


@router.get("/api/events", response_model=list[EventOut])
def list_events(db: Session = Depends(get_db)) -> list[EventOut]:
    event_rows = list_events_with_inventory(db)
    return [EventOut(**row) for row in event_rows]


@router.get("/api/events/{event_id}/seats")
def list_event_seats(event_id: int, db: Session = Depends(get_db)) -> list[dict]:
    event = db.get(Event, event_id)
    if not event:
        return []
    seats = db.execute(select(Seat).where(Seat.event_id == event_id).order_by(Seat.row_label, Seat.seat_number)).scalars().all()
    return [
        {
            "id": seat.id,
            "row_label": seat.row_label,
            "seat_number": seat.seat_number,
            "is_available": seat.is_available,
            "price_override": float(seat.price_override) if seat.price_override is not None else None,
        }
        for seat in seats
    ]


@router.post("/api/events", response_model=EventOut)
def create_event_endpoint(payload: EventCreate, db: Session = Depends(get_db)) -> EventOut:
    event = create_event(
        db,
        organizer_id=payload.organizer_id,
        title=payload.title,
        description=payload.description,
        venue=payload.venue,
        start_time=payload.start_time,
        end_time=payload.end_time,
        base_price=payload.base_price,
        row_count=payload.row_count,
        seats_per_row=payload.seats_per_row,
    )
    event_rows = [row for row in list_events_with_inventory(db) if row["id"] == event.id]
    return EventOut(**event_rows[0])


@router.patch("/api/events/{event_id}/status", response_model=EventOut)
def update_event_status_endpoint(event_id: int, payload: EventStatusUpdate, db: Session = Depends(get_db)) -> EventOut:
    update_event_status(db, event_id, payload.status)
    event_rows = [row for row in list_events_with_inventory(db) if row["id"] == event_id]
    return EventOut(**event_rows[0])


@router.post("/api/bookings", response_model=BookingOut)
def create_booking_endpoint(payload: BookingCreate, db: Session = Depends(get_db)) -> BookingOut:
    booking = create_booking(
        db,
        customer_id=payload.customer_id,
        event_id=payload.event_id,
        seat_ids=payload.seat_ids,
        offer_code=payload.offer_code,
    )
    return booking_to_out(booking)


@router.post("/api/bookings/{booking_id}/pay", response_model=BookingOut)
def pay_booking_endpoint(booking_id: int, payload: PaymentCapture, db: Session = Depends(get_db)) -> BookingOut:
    booking = capture_payment(
        db,
        booking_id=booking_id,
        customer_id=payload.customer_id,
        method=payload.method,
        mark_success=payload.mark_success,
    )
    return booking_to_out(booking)


@router.get("/api/bookings/{booking_id}", response_model=BookingOut)
def get_booking(booking_id: int, db: Session = Depends(get_db)) -> BookingOut:
    booking = db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.booking_seats).selectinload(BookingSeat.ticket),
            selectinload(Booking.payment),
            selectinload(Booking.refund),
        )
    ).scalar_one_or_none()
    if not booking:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Booking not found")
    return booking_to_out(booking)


@router.get("/api/customers/{customer_id}/bookings", response_model=list[BookingOut])
def get_customer_booking_history(customer_id: int, db: Session = Depends(get_db)) -> list[BookingOut]:
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
    return [booking_to_out(b) for b in bookings]


@router.post("/api/bookings/{booking_id}/refund-request")
def refund_request_endpoint(booking_id: int, payload: RefundRequestCreate, db: Session = Depends(get_db)) -> dict:
    refund = request_refund(db, booking_id=booking_id, customer_id=payload.customer_id, reason=payload.reason)
    return {"refund_id": refund.id, "status": refund.status, "amount": float(refund.refund_amount)}


@router.post("/api/bookings/{booking_id}/refund-decision")
def refund_decision_endpoint(booking_id: int, payload: RefundDecision, db: Session = Depends(get_db)) -> dict:
    refund = decide_refund(
        db,
        booking_id=booking_id,
        support_executive_id=payload.support_executive_id,
        approve=payload.approve,
    )
    return {"refund_id": refund.id, "status": refund.status, "resolved_by": refund.resolved_by}


@router.post("/api/tickets/validate", response_model=TicketValidationOut)
def validate_ticket_endpoint(payload: TicketValidation, db: Session = Depends(get_db)) -> TicketValidationOut:
    is_valid, message, ticket = validate_ticket(db, qr_code=payload.qr_code, entry_manager_id=payload.entry_manager_id)
    return TicketValidationOut(valid=is_valid, message=message, ticket_status=ticket.status if ticket else None)


@router.post("/api/complaints")
def complaint_create_endpoint(payload: ComplaintCreate, db: Session = Depends(get_db)) -> dict:
    complaint = create_complaint(
        db,
        customer_id=payload.customer_id,
        booking_id=payload.booking_id,
        event_id=payload.event_id,
        subject=payload.subject,
        description=payload.description,
    )
    return {"complaint_id": complaint.id, "status": complaint.status}


@router.patch("/api/complaints/{complaint_id}")
def complaint_update_endpoint(complaint_id: int, payload: ComplaintUpdate, db: Session = Depends(get_db)) -> dict:
    complaint = update_complaint(
        db,
        complaint_id=complaint_id,
        support_executive_id=payload.support_executive_id,
        new_status=payload.status,
        resolution=payload.resolution,
    )
    return {"complaint_id": complaint.id, "status": complaint.status, "resolution": complaint.resolution}


@router.get("/api/complaints")
def complaint_list_endpoint(db: Session = Depends(get_db)) -> list[dict]:
    complaints = db.execute(select(SupportTicket).order_by(SupportTicket.created_at.desc())).scalars().all()
    return [
        {
            "id": c.id,
            "customer_id": c.customer_id,
            "booking_id": c.booking_id,
            "event_id": c.event_id,
            "subject": c.subject,
            "description": c.description,
            "status": c.status,
            "assigned_to": c.assigned_to,
            "resolution": c.resolution,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        for c in complaints
    ]


@router.get("/api/offers")
def list_offers(db: Session = Depends(get_db)) -> list[dict]:
    offers = db.execute(select(Offer).order_by(Offer.code)).scalars().all()
    return [
        {
            "id": offer.id,
            "code": offer.code,
            "offer_type": offer.offer_type,
            "value": offer.value,
            "active": offer.active,
            "used_count": offer.used_count,
            "usage_limit": offer.usage_limit,
            "valid_until": offer.valid_until,
        }
        for offer in offers
    ]


@router.get("/api/analytics")
def analytics_endpoint(db: Session = Depends(get_db)) -> dict:
    bookings = db.execute(select(Booking)).scalars().all()
    total_bookings = len(bookings)
    confirmed = sum(1 for b in bookings if b.status == BookingStatus.confirmed)
    refunded = sum(1 for b in bookings if b.status == BookingStatus.refunded)
    total_sales = sum(float(b.total_amount) for b in bookings if b.status in {BookingStatus.confirmed, BookingStatus.refund_requested})
    return {
        "total_bookings": total_bookings,
        "confirmed_bookings": confirmed,
        "refunded_bookings": refunded,
        "gross_sales": round(total_sales, 2),
    }


@router.get("/api/bookings/{booking_id}/ticket-download", response_class=PlainTextResponse)
def ticket_download_simulation(booking_id: int, db: Session = Depends(get_db)) -> str:
    booking = db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(selectinload(Booking.booking_seats).selectinload(BookingSeat.ticket))
    ).scalar_one_or_none()
    if not booking:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Booking not found")

    lines = [
        "Event Ticket (Simulation)",
        f"Booking ID: {booking.id}",
        f"Customer ID: {booking.customer_id}",
        f"Event ID: {booking.event_id}",
        f"Status: {booking.status.value}",
        "Ticket Codes:",
    ]
    for code in [link.ticket.qr_code for link in booking.booking_seats if link.ticket]:
        lines.append(f"- {code}")
    return "\n".join(lines)


@router.get("/api/bookings/{booking_id}/confirmation-email", response_class=PlainTextResponse)
def confirmation_email_simulation(booking_id: int, db: Session = Depends(get_db)) -> str:
    booking = db.get(Booking, booking_id)
    if not booking:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Booking not found")
    return (
        f"To: customer_id_{booking.customer_id}@mail.local\n"
        f"Subject: Booking #{booking.id} confirmation\n\n"
        f"Your booking for event {booking.event_id} is currently {booking.status.value}.\n"
        f"Amount: {float(booking.total_amount):.2f}"
    )
