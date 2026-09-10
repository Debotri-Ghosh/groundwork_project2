"""
Creates the Groundwork database schema: contracts + clauses tables.
Run once. Safe to re-run (won't duplicate tables).

Usage: python init_db.py
"""
import os
import sys

# Windows consoles (cp1252) can't print some Unicode — force UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://groundwork:groundwork2026@localhost:5432/groundwork_db")
engine = create_engine(DATABASE_URL)
Base = declarative_base()


class Contract(Base):
    __tablename__ = "contracts"

    contract_id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String, unique=True, nullable=False)
    document_name = Column(String)
    raw_text = Column(Text)

    clauses = relationship("Clause", back_populates="contract", cascade="all, delete-orphan")


class Clause(Base):
    __tablename__ = "clauses"

    clause_id = Column(Integer, primary_key=True, autoincrement=True)
    contract_id = Column(Integer, ForeignKey("contracts.contract_id"), nullable=False)
    category = Column(String, nullable=False)
    extracted_text = Column(Text)   # raw quoted span(s) from the contract
    answer = Column(Text)           # normalized answer (e.g. Yes/No, a date, a name)

    contract = relationship("Contract", back_populates="clauses")


if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print(f"Schema created in {DATABASE_URL}")
    print("Tables: contracts, clauses")
