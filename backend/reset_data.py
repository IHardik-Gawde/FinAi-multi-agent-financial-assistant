"""Destructively clear AI Finance Employee data while preserving source code/configuration.

Run from the project root:
    python full_project_data_reset.py

The script requires typing DELETE to proceed.
"""

from pathlib import Path
import shutil
import tempfile

from database.db import engine
from database import models  # noqa: F401 - registers every ORM table
from sqlalchemy import MetaData, inspect, text

SCRIPT_DIR = Path(__file__).resolve().parent
# reset_data.py is stored in backend/, while the command is run from the
# repository root (python -m backend.reset_data).
PROJECT_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name.lower() == "backend" else SCRIPT_DIR

# Data/output directories known to hold uploaded documents, vector data,
# extraction artifacts, logs, and generated run results. Only contents are removed.
PROJECT_DATA_DIRS = [
    PROJECT_ROOT / "data",
    PROJECT_ROOT / "results",
    PROJECT_ROOT / "logs",
    PROJECT_ROOT / "outputs",
    PROJECT_ROOT / "uploads",
    PROJECT_ROOT / "temp",
    PROJECT_ROOT / "tmp",
]

# Some project layouts keep runtime artifacts under backend/ instead.
BACKEND_DIR = PROJECT_ROOT / "backend"
if BACKEND_DIR.is_dir():
    PROJECT_DATA_DIRS.extend(
        BACKEND_DIR / name
        for name in ("data", "results", "logs", "outputs", "uploads", "temp", "tmp")
    )

# The document manager's pending-upload staging directory.
SYSTEM_TEMP_DIRS = [Path(tempfile.gettempdir()) / "ai_finance_pending_documents"]


def clear_directory_contents(directory: Path) -> int:
    removed = 0
    if not directory.exists() or not directory.is_dir():
        return removed
    for child in directory.iterdir():
        try:
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed += 1
        except Exception as exc:
            print(f"[WARNING] Could not remove {child}: {exc}")
    return removed


def clear_database() -> dict[str, int]:
    # Reflect the actual database instead of assuming every ORM table has
    # already been created. This also includes tables not registered in Base.
    counts: dict[str, int] = {}
    with engine.begin() as connection:
        if connection.dialect.name == "sqlite":
            connection.execute(text("PRAGMA foreign_keys=ON"))

        existing = MetaData()
        existing.reflect(bind=connection)
        existing_names = set(inspect(connection).get_table_names())

        # Reverse dependency order handles child tables before parent tables.
        for table in reversed(existing.sorted_tables):
            if table.name not in existing_names:
                continue
            result = connection.execute(table.delete())
            counts[table.name] = max(result.rowcount or 0, 0)

    return counts


def main() -> None:
    print("AI FINANCE EMPLOYEE — FULL DATA RESET")
    print(
        "This deletes ALL rows from all registered database tables, including customers, invoices and transactions."
    )
    print(
        "It also clears contents of the project data/results/logs/outputs/uploads/temp/tmp "
        "and pending-upload staging directories."
    )
    print("Project source code and configuration files are not targeted.")
    print("\nDirectories to clear:")
    for path in PROJECT_DATA_DIRS + SYSTEM_TEMP_DIRS:
        print(f" - {path}")
    confirmation = input("\nType DELETE to permanently continue: ").strip()
    if confirmation != "DELETE":
        print("Cancelled. No data was deleted.")
        return

    table_counts = clear_database()
    print("\nDatabase rows deleted:")
    for table_name, count in table_counts.items():
        print(f" - {table_name}: {count}")

    print("\nFilesystem entries removed:")
    for directory in PROJECT_DATA_DIRS + SYSTEM_TEMP_DIRS:
        count = clear_directory_contents(directory)
        print(f" - {directory}: {count} top-level entries")

    # Remove Python bytecode caches, which are generated artifacts, not source code.
    cache_count = 0
    for cache_dir in PROJECT_ROOT.rglob("__pycache__"):
        # Avoid traversing/removing caches inside virtual environments.
        if any(
            part.lower() in {".venv", "venv", "env", "site-packages"}
            for part in cache_dir.parts
        ):
            continue
        try:
            shutil.rmtree(cache_dir)
            cache_count += 1
        except Exception as exc:
            print(f"[WARNING] Could not remove {cache_dir}: {exc}")
    print(f" - Python __pycache__ directories removed: {cache_count}")

    print(
        "\nRESET COMPLETE. Database schema and project code/configuration were preserved."
    )
    print(
        "Restart the backend and any running agent processes before uploading fresh documents."
    )


if __name__ == "__main__":
    main()
