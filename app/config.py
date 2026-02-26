import os

from pydantic import BaseModel


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class Settings(BaseModel):
    app_name: str = os.getenv("APP_NAME", "Online Event Ticket Booking Platform")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./ticketing.db")
    currency: str = os.getenv("CURRENCY", "USD")
    tax_rate: float = float(os.getenv("TAX_RATE", "0.08"))
    smtp_host: str | None = os.getenv("SMTP_HOST")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str | None = os.getenv("SMTP_USERNAME")
    smtp_password: str | None = os.getenv("SMTP_PASSWORD")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", "noreply@ticket.local")
    smtp_use_tls: bool = _as_bool(os.getenv("SMTP_USE_TLS"), True)
    smtp_use_ssl: bool = _as_bool(os.getenv("SMTP_USE_SSL"), False)


settings = Settings()
