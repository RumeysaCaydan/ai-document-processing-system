from sqlalchemy import Column, Integer, String
from database.database import Base

class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    iban = Column(String)
    amount = Column(String)

