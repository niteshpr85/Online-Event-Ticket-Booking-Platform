from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import Base, SessionLocal, engine
from app.migrations import run_migrations
from app.routes import router
from app.services import seed_initial_data


app = FastAPI(title="Online Event Ticket Booking Platform", version="1.0.0")
app.include_router(router)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)
    db = SessionLocal()
    try:
        seed_initial_data(db)
    finally:
        db.close()
