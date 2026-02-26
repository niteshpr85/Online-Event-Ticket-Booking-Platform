from datetime import datetime

from pydantic import BaseModel, Field

from app.models import (
    BookingStatus,
    EventStatus,
    PaymentStatus,
    RefundStatus,
    SupportStatus,
    TicketStatus,
    UserRole,
)


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    role: UserRole

    class Config:
        from_attributes = True


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=6, max_length=120)
    role: UserRole = UserRole.customer


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=120)
    password: str = Field(min_length=6, max_length=120)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=5, max_length=120)


class ForgotPasswordResponse(BaseModel):
    sent: bool
    mode: str
    message: str
    reset_token: str | None = None


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=8, max_length=300)
    new_password: str = Field(min_length=6, max_length=120)


class ResetPasswordResponse(BaseModel):
    success: bool
    message: str


class EventDetailEmailRequest(BaseModel):
    customer_id: int
    event_id: int


class EventDetailEmailResponse(BaseModel):
    sent: bool
    mode: str
    to_email: str
    subject: str
    body: str


class AIChatRequest(BaseModel):
    user_id: int
    user_role: UserRole
    message: str = Field(min_length=1, max_length=2000)


class AIChatResponse(BaseModel):
    mode: str
    answer: str


class EventCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10)
    venue: str = Field(min_length=3, max_length=160)
    start_time: datetime
    end_time: datetime
    base_price: float = Field(gt=0)
    row_count: int = Field(ge=1, le=26)
    seats_per_row: int = Field(ge=1, le=50)
    organizer_id: int


class EventStatusUpdate(BaseModel):
    status: EventStatus


class EventOut(BaseModel):
    id: int
    title: str
    description: str
    venue: str
    start_time: datetime
    end_time: datetime
    base_price: float
    status: EventStatus
    organizer_id: int
    total_seats: int
    available_seats: int


class BookingCreate(BaseModel):
    customer_id: int
    event_id: int
    seat_ids: list[int] = Field(min_length=1)
    offer_code: str | None = None


class PaymentCapture(BaseModel):
    customer_id: int
    method: str = Field(min_length=2, max_length=40)
    mark_success: bool = True


class RefundRequestCreate(BaseModel):
    customer_id: int
    reason: str = Field(min_length=5, max_length=250)


class RefundDecision(BaseModel):
    support_executive_id: int
    approve: bool


class TicketValidation(BaseModel):
    qr_code: str
    entry_manager_id: int


class ComplaintCreate(BaseModel):
    customer_id: int
    booking_id: int | None = None
    event_id: int | None = None
    subject: str = Field(min_length=3, max_length=120)
    description: str = Field(min_length=10)


class ComplaintUpdate(BaseModel):
    support_executive_id: int
    status: SupportStatus
    resolution: str | None = None


class BookingOut(BaseModel):
    id: int
    customer_id: int
    event_id: int
    status: BookingStatus
    subtotal: float
    discount_amount: float
    tax_amount: float
    total_amount: float
    offer_code: str | None
    ticket_codes: list[str]
    payment_status: PaymentStatus | None
    refund_status: RefundStatus | None


class TicketValidationOut(BaseModel):
    valid: bool
    message: str
    ticket_status: TicketStatus | None = None
