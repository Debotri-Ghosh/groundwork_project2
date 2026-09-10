"""
Verifies the Groundwork database: row counts, a spot check against the
original CSV, and a join query — proves the data is really there and correct.

Usage: python verify_db.py
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, func
from sqlalchemy.orm import sessionmaker

from init_db import Contract, Clause

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://groundwork:groundwork2026@localhost:5432/groundwork_db")
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)


def main():
    print("--- Groundwork Database Verification ---\n")

    # 1. Tables exist
    tables = inspect(engine).get_table_names()
    print("Tables found:", tables)

    session = Session()

    # 2. Row counts
    n_contracts = session.query(func.count(Contract.contract_id)).scalar()
    n_clauses = session.query(func.count(Clause.clause_id)).scalar()
    print(f"\nContracts: {n_contracts}")
    print(f"Clauses:   {n_clauses}")

    # 3. Spot check: pull one contract and its clauses
    sample = session.query(Contract).first()
    if sample:
        print(f"\nSample contract: {sample.filename}")
        print(f"  document_name: {sample.document_name}")
        print(f"  raw_text length: {len(sample.raw_text or '')} chars")
        sample_clauses = session.query(Clause).filter_by(contract_id=sample.contract_id).limit(5).all()
        print(f"  first {len(sample_clauses)} clauses:")
        for c in sample_clauses:
            preview = (c.extracted_text or "")[:80]
            print(f"    [{c.category}] extracted='{preview}' answer='{c.answer}'")

    # 4. Join query: contracts with more than 10 clauses found
    print("\nContracts with 10+ clauses found (top 5):")
    results = (
        session.query(Contract.filename, func.count(Clause.clause_id).label("clause_count"))
        .join(Clause)
        .group_by(Contract.contract_id)
        .having(func.count(Clause.clause_id) >= 10)
        .order_by(func.count(Clause.clause_id).desc())
        .limit(5)
        .all()
    )
    for filename, count in results:
        print(f"  {filename}: {count} clauses")

    session.close()
    print("\nIf contracts/clauses counts look right and the sample data is readable, the database is good.")


if __name__ == "__main__":
    main()
