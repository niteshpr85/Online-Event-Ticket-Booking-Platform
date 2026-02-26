from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, Event, Offer, SupportStatus, SupportTicket, UserRole


def _build_user_context(db: Session, *, user_id: int, user_role: str) -> str:
    events = db.execute(select(Event).order_by(Event.start_time.asc()).limit(5)).scalars().all()
    offers = db.execute(select(Offer).where(Offer.active.is_(True)).order_by(Offer.code.asc()).limit(5)).scalars().all()

    lines: list[str] = [
        f"Current UTC time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}",
        f"Logged in user id: {user_id}",
        f"Logged in role: {user_role}",
        "Upcoming events:",
    ]
    for event in events:
        lines.append(
            f"- #{event.id} {event.title} at {event.venue} ({event.start_time.strftime('%Y-%m-%d %H:%M')}) status={event.status.value}"
        )

    if user_role == UserRole.customer.value:
        bookings = (
            db.execute(select(Booking).where(Booking.customer_id == user_id).order_by(Booking.created_at.desc()).limit(5))
            .scalars()
            .all()
        )
        lines.append("Recent bookings:")
        for booking in bookings:
            lines.append(
                f"- booking #{booking.id} event={booking.event_id} status={booking.status.value} total={float(booking.total_amount):.2f}"
            )

    open_complaints = (
        db.execute(
            select(SupportTicket)
            .where(SupportTicket.status.in_([SupportStatus.open, SupportStatus.in_progress]))
            .order_by(SupportTicket.created_at.desc())
            .limit(5)
        )
        .scalars()
        .all()
    )
    lines.append("Open complaints snapshot:")
    for complaint in open_complaints:
        lines.append(f"- complaint #{complaint.id} status={complaint.status.value} subject={complaint.subject}")

    lines.append("Active offer codes:")
    for offer in offers:
        lines.append(f"- {offer.code} ({offer.offer_type.value} {offer.value})")
    return "\n".join(lines)


def _rule_based_reply(message: str, *, user_role: str) -> str:
    text = message.lower()
    if "book" in text or "seat" in text:
        return "Go to Customer tab -> Create Booking. Pick event, select available seats, then click Book Seats."
    if "pay" in text or "payment" in text:
        return "Use Customer tab -> Payment Simulation. Enter booking id, method, and capture payment."
    if "refund" in text:
        return "Customers request refund in Customer tab. Support/Admin processes it in Support tab or Admin queue."
    if "ticket" in text and ("validate" in text or "entry" in text):
        return "Use Entry Manager tab -> Ticket Validation with ticket QR code and entry manager id."
    if "complaint" in text or "support" in text:
        return "Create complaints in Customer tab and update them in Support Executive tab."
    if "offer" in text or "discount" in text:
        return "Use codes like WELCOME10 or FLAT5 during booking in the Offer Code field."
    if "admin" in text:
        return "Admin controls are in the Admin Control Center tab for event commands, user directory, and queues."
    if user_role == UserRole.customer.value:
        return "I can help with booking, payment, refunds, and event details. Ask me a specific task."
    return "I can help with operations in this platform. Ask about booking, payment, validation, refund, complaints, or events."


def get_ai_chat_response(db: Session, *, user_id: int, user_role: str, message: str) -> dict:
    context = _build_user_context(db, user_id=user_id, user_role=user_role)
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    if not api_key:
        return {"mode": "fallback", "answer": _rule_based_reply(message, user_role=user_role)}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "You are an assistant for an Event Ticket Booking Platform. "
                                "Use the provided context and give short, actionable answers."
                            ),
                        }
                    ],
                },
                {"role": "system", "content": [{"type": "text", "text": context}]},
                {"role": "user", "content": [{"type": "text", "text": message}]},
            ],
            max_output_tokens=300,
        )
        text = getattr(response, "output_text", None)
        if not text:
            text = _rule_based_reply(message, user_role=user_role)
            return {"mode": "fallback", "answer": text}
        return {"mode": "openai", "answer": text}
    except Exception:
        return {"mode": "fallback", "answer": _rule_based_reply(message, user_role=user_role)}
