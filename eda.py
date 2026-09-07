import json
import os
import re
import pandas as pd
import matplotlib.pyplot as plt

# ============================================================
# CONFIGURATION
# ============================================================

JSON_PATH = r"data\cuad\CUAD_v1\CUAD_v1.json"
CLAUSES_PATH = r"data\cuad\CUAD_v1\master_clauses.csv"

OUTPUT_DIR = "eda_results"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# LOAD CUAD JSON
# ============================================================

print("\nLoading CUAD dataset...")

with open(JSON_PATH, "r", encoding="utf-8") as f:
    dataset = json.load(f)

contracts = dataset["data"]

print(f"Contracts found: {len(contracts)}")


# ============================================================
# CONTRACT-LEVEL EDA
# ============================================================

contract_records = []

for contract in contracts:
    title = contract.get("title", "")

    # Combine all paragraph contexts belonging to the contract
    contexts = []

    for paragraph in contract.get("paragraphs", []):
        context = paragraph.get("context", "")
        if context:
            contexts.append(context)

    full_text = "\n".join(contexts)

    words = re.findall(r"\b\w+\b", full_text)

    contract_records.append({
        "contract": title,
        "characters": len(full_text),
        "words": len(words),
        "paragraphs": len(contract.get("paragraphs", []))
    })


contract_df = pd.DataFrame(contract_records)


# ============================================================
# DATASET SUMMARY
# ============================================================

print("\n" + "=" * 60)
print("DATASET SUMMARY")
print("=" * 60)

print(f"Total contracts        : {len(contract_df):,}")
print(f"Total characters       : {contract_df['characters'].sum():,}")
print(f"Total words            : {contract_df['words'].sum():,}")
print(f"Average words/contract : {contract_df['words'].mean():,.0f}")
print(f"Median words/contract  : {contract_df['words'].median():,.0f}")
print(f"Minimum words          : {contract_df['words'].min():,}")
print(f"Maximum words          : {contract_df['words'].max():,}")


# ============================================================
# DATA QUALITY CHECKS
# ============================================================

print("\n" + "=" * 60)
print("DATA QUALITY")
print("=" * 60)

empty_contracts = (contract_df["words"] == 0).sum()

print(f"Empty contracts        : {empty_contracts}")
print(f"Duplicate titles       : {contract_df['contract'].duplicated().sum()}")
print(f"Missing titles         : {contract_df['contract'].isna().sum()}")


# ============================================================
# CLAUSE / ANNOTATION ANALYSIS
# ============================================================

print("\n" + "=" * 60)
print("ANNOTATION ANALYSIS")
print("=" * 60)

annotation_records = []

for contract in contracts:

    title = contract.get("title", "")

    for paragraph in contract.get("paragraphs", []):

        for qa in paragraph.get("qas", []):

            question = qa.get("question", "")

            annotation_records.append({
                "contract": title,
                "question": question,
                "answers": len(qa.get("answers", []))
            })


annotation_df = pd.DataFrame(annotation_records)

print(f"Total QA/annotations    : {len(annotation_df):,}")

if not annotation_df.empty:

    print("\nTop annotation/question categories:")
    print(
        annotation_df["question"]
        .value_counts()
        .head(15)
        .to_string()
    )

    annotation_df["question"].value_counts().to_csv(
        os.path.join(OUTPUT_DIR, "annotation_distribution.csv")
    )


# ============================================================
# CONTRACT LENGTH STATISTICS
# ============================================================

length_stats = contract_df["words"].describe()

print("\n" + "=" * 60)
print("CONTRACT LENGTH STATISTICS")
print("=" * 60)

print(length_stats)


# Save contract statistics
contract_df.to_csv(
    os.path.join(OUTPUT_DIR, "contract_statistics.csv"),
    index=False
)


# ============================================================
# MASTER CLAUSES VALIDATION
# ============================================================

print("\n" + "=" * 60)
print("NORMALIZED CLAUSE DATASET")
print("=" * 60)

if os.path.exists(CLAUSES_PATH):

    clauses_df = pd.read_csv(CLAUSES_PATH)

    print(f"Rows in master_clauses.csv : {len(clauses_df):,}")
    print(f"Columns                    : {len(clauses_df.columns)}")

    print("\nColumns:")
    print(list(clauses_df.columns))

    print("\nMissing values:")
    print(clauses_df.isna().sum())

    print("\nDuplicate rows:")
    print(clauses_df.duplicated().sum())

else:
    print("master_clauses.csv not found.")


# ============================================================
# GRAPH 1 — CONTRACT LENGTH DISTRIBUTION
# ============================================================

plt.figure(figsize=(10, 6))

plt.hist(
    contract_df["words"],
    bins=30
)

plt.xlabel("Words per contract")
plt.ylabel("Number of contracts")
plt.title("CUAD Contract Length Distribution")

plt.tight_layout()

plt.savefig(
    os.path.join(OUTPUT_DIR, "contract_length_distribution.png"),
    dpi=200
)

plt.close()


# ============================================================
# GRAPH 2 — TOP ANNOTATION CATEGORIES
# ============================================================

if not annotation_df.empty:

    top_categories = annotation_df["question"].value_counts().head(15)

    plt.figure(figsize=(12, 7))

    top_categories.sort_values().plot(kind="barh")

    plt.xlabel("Number of annotations")
    plt.ylabel("Clause / Question Category")
    plt.title("Top 15 CUAD Annotation Categories")

    plt.tight_layout()

    plt.savefig(
        os.path.join(OUTPUT_DIR, "annotation_distribution.png"),
        dpi=200
    )

    plt.close()


# ============================================================
# GRAPH 3 — ANNOTATIONS PER CONTRACT
# ============================================================

if not annotation_df.empty:

    annotations_per_contract = (
        annotation_df
        .groupby("contract")
        .size()
    )

    plt.figure(figsize=(10, 6))

    plt.hist(
        annotations_per_contract,
        bins=30
    )

    plt.xlabel("Annotations per contract")
    plt.ylabel("Number of contracts")
    plt.title("Annotation Coverage Across Contracts")

    plt.tight_layout()

    plt.savefig(
        os.path.join(OUTPUT_DIR, "annotations_per_contract.png"),
        dpi=200
    )

    plt.close()


# ============================================================
# FINAL SUMMARY
# ============================================================

print("\n" + "=" * 60)
print("EDA COMPLETE")
print("=" * 60)

print(f"""
Results saved to:

{OUTPUT_DIR}\\

Files generated:
- contract_statistics.csv
- annotation_distribution.csv
- contract_length_distribution.png
- annotation_distribution.png
- annotations_per_contract.png
""")