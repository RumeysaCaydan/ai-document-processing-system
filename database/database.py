from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

DATEBASE_URL = "postgresql://postgres:mit.2021A@localhost:5432//document_ai_db"

#engine(connect with database)
engine=create_engine(DATEBASE_URL)

#session(for data exchange)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

#Base (will use for define a model)

Base= declerative_base()

