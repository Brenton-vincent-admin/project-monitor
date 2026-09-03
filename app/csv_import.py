import csv
from pathlib import Path


def import_accounts_from_csv(csv_path, db):
    """Import accounts from a CSV file into the database.
    Expected CSV format: Name,Token (with header row).
    Returns the number of accounts imported.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    count = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        if "token" not in headers:
            raise ValueError(f"CSV must have a 'Token' column. Found: {headers}")

        name_col = next((h for h in headers if h == "name"), None)

        for row in reader:
            token = row.get("Token") or row.get("token", "")
            token = token.strip()
            if not token:
                continue

            name = ""
            if name_col:
                name = (row.get("Name") or row.get(name_col, "")).strip()
            if not name:
                name = f"Account {count + 1}"

            db.add_account(name, token)
            count += 1

    return count


def preview_csv(csv_path):
    """Return (headers, first few rows) from a CSV file."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = []
        for i, row in enumerate(reader):
            if i >= 5:
                break
            rows.append(row)
        return headers, rows
