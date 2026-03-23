from fastapi import FastAPI
from database.database import SessionLocal
from database.models import Receipt

app = FastAPI()


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/test-db")
def test_db():
    db = SessionLocal()

    new_receipt = Receipt(
        name="Test User",
        iban="TR123456789",
        amount="1000"
    )

    db.add(new_receipt)
    db.commit()
    db.close()

    return {"message": "Veri eklendi"}