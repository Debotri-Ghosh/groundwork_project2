"""
Loads CUAD's master_clauses.csv + contract text files into the database
created by init_db.py.

Usage: python load_cuad.py
"""
import os
import ast
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from init_db import Contract, Clause, Base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://groundwork:groundwork2026@localhost:5432/groundwork_db")
CSV_PATH = os.path.join("data", "cuad", "CUAD_v1", "master_clauses.csv")
TXT_ROOT = os.path.join("data", "cuad", "CUAD_v1", "full_contract_txt")

engine = create_engine(DATABASE_URL)
Base.metadata.create_all(engine)  # safe if already created
Session = sessionmaker(bind=engine)


def build_txt_index():
    """Map each contract's base filename (no extension) to its full .txt path,
    since files live nested under Part_I / Part_II / Part_III subfolders."""
    index = {}
    for root, _, files in os.walk(TXT_ROOT):
        for fname in files:
            if fname.lower().endswith(".txt"):
                base = os.path.splitext(fname)[0]
                index[base] = os.path.join(root, fname)
    return index


def parse_list_field(value):
    """CUAD stores extracted quotes as a string like "['text one', 'text two']".
    Returns a cleaned single string, or empty string if nothing extracted."""
    if pd.isna(value) or value == "" or value == "[]":
        return ""
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, list):
            return " | ".join(str(x) for x in parsed if str(x).strip())
        return str(parsed)
    except (ValueError, SyntaxError):
        return str(value)


def main():
    if not os.path.exists(CSV_PATH):
        print(f"  {CSV_PATH} not found. Run extract_cuad.py first.")
        return

    df = pd.read_csv(CSV_PATH)
    txt_index = build_txt_index()
    print(f"  loaded CSV: {df.shape[0]} contracts, {df.shape[1]} columns")
    print(f"  found {len(txt_index)} .txt contract files")

    # Category columns come in pairs: "<Category>" and "<Category>-Answer" or "<Category>- Answer"
    non_category_cols = {"Filename", "Document Name", "Document Name-Answer"}
    raw_cols = [
        c for c in df.columns
        if c not in non_category_cols and not c.rstrip().endswith("Answer")
    ]

    session = Session()
    contracts_added, clauses_added, missing_txt, skipped_dups = 0, 0, 0, 0
    seen_filenames = set()

    for _, row in df.iterrows():
        filename = str(row["Filename"])

        # CUAD's CSV contains a few duplicate rows — keep the first only
        if filename in seen_filenames:
            skipped_dups += 1
            continue
        seen_filenames.add(filename)

        base = os.path.splitext(filename)[0]

        txt_path = txt_index.get(base)
        raw_text = ""
        if txt_path:
            try:
                with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
                    raw_text = f.read()
            except Exception as e:
                print(f"    warning: couldn't read {txt_path}: {e}")
        else:
            missing_txt += 1

        contract = Contract(
            filename=filename,
            document_name=str(row.get("Document Name-Answer", "")),
            raw_text=raw_text,
        )
        session.add(contract)
        session.flush()  # get contract.contract_id before adding clauses
        contracts_added += 1

        for category in raw_cols:
            answer_col = category + "-Answer"
            if answer_col not in df.columns:
                answer_col = category + "- Answer"  # CUAD has one inconsistent column name
            extracted = parse_list_field(row.get(category, ""))
            answer = row.get(answer_col, "") if answer_col in df.columns else ""
            answer = "" if pd.isna(answer) else str(answer)

            if extracted or answer:
                clause = Clause(
                    contract_id=contract.contract_id,
                    category=category,
                    extracted_text=extracted,
                    answer=answer,
                )
                session.add(clause)
                clauses_added += 1

    session.commit()
    session.close()

    print(f"\n  contracts loaded: {contracts_added}")
    print(f"  clauses loaded: {clauses_added}")
    print(f"  contracts missing a matching .txt file: {missing_txt}")
    print(f"  duplicate CSV rows skipped: {skipped_dups}")


if __name__ == "__main__":
    main()
