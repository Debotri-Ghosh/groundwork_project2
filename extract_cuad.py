"""
Extracts CUAD_v1.zip safely on Windows, working around the 260-character
path length limit and skipping the PDF files we don't need
(we use the .txt contracts + master_clauses.csv instead).

Run this AFTER download_cuad.py has already downloaded the zip.
Usage: python extract_cuad.py
"""
import os
import zipfile

CUAD_DIR = os.path.join("data", "cuad")
ZIP_PATH = os.path.join(CUAD_DIR, "CUAD_v1.zip")
EXTRACT_ROOT = os.path.join(CUAD_DIR, "CUAD_v1")


def long_path(path):
    """Prefix with \\\\?\\ so Windows allows paths beyond 260 chars,
    even without the LongPathsEnabled registry setting (which needs admin)."""
    abs_path = os.path.abspath(path)
    if os.name == "nt" and not abs_path.startswith("\\\\?\\"):
        return "\\\\?\\" + abs_path
    return abs_path


def should_skip(member_name):
    # Skip PDFs entirely — we don't need them and they cause most of the
    # long-path failures. Keep: master_clauses.csv, full_contract_txt/*, CUAD_v1.json
    return "full_contract_pdf" in member_name


def main():
    if not os.path.exists(ZIP_PATH):
        print(f"  {ZIP_PATH} not found — run download_cuad.py first.")
        return

    print("  extracting (skipping PDFs)...")
    extracted, skipped, failed = 0, 0, []

    with zipfile.ZipFile(ZIP_PATH, "r") as z:
        for member in z.infolist():
            if member.is_dir():
                continue
            if should_skip(member.filename):
                skipped += 1
                continue

            target_path = os.path.join(CUAD_DIR, member.filename)
            target_dir = os.path.dirname(target_path)

            try:
                os.makedirs(long_path(target_dir), exist_ok=True)
                with z.open(member) as source:
                    data = source.read()
                with open(long_path(target_path), "wb") as f:
                    f.write(data)
                extracted += 1
            except Exception as e:
                failed.append((member.filename, str(e)))

    print(f"  extracted: {extracted} files")
    print(f"  skipped (PDFs): {skipped} files")
    if failed:
        print(f"  failed: {len(failed)} files (first 5 shown)")
        for name, err in failed[:5]:
            print(f"    {name}: {err}")
    else:
        print("  no failures.")

    print("\n  CUAD ready in:", EXTRACT_ROOT)


if __name__ == "__main__":
    main()
