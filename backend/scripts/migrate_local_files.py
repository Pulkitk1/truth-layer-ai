"""Copy PDFs from the old local file store (backend/storage/) into the database (table file_objects).

Earlier versions kept uploaded PDFs and generated reports as files under backend/storage/documents/ and
backend/storage/reports/. PDFs are now stored in Neon. This script copies any files that are left over, VERIFIES each copy
(it reads the file back from the database and compares its SHA-256 with the local file), and never deletes anything
unless you pass --delete-verified-local, and then only the local files whose database copy was just verified.

    cd backend
    .\\.venv\\Scripts\\python scripts\\migrate_local_files.py                       # copy + verify, keep local files
    .\\.venv\\Scripts\\python scripts\\migrate_local_files.py --delete-verified-local  # ...then remove the verified local files
    .\\.venv\\Scripts\\python scripts\\migrate_local_files.py --dir D:\\old\\storage     # another folder

Files whose document or report no longer exists in the database are reported and left alone."""
import argparse
import hashlib
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app import filestore  # noqa: E402
from app.db.models import Document, FileObject, Report  # noqa: E402
from app.db.session import session_scope  # noqa: E402

NAME = re.compile(r"^([0-9a-f]{32})\.pdf$")


def migrate(root: Path, delete_local: bool = False) -> dict:
    store = filestore.get_store()
    out = {"copied": 0, "already_in_database": 0, "verified": 0, "skipped_no_record": 0, "failed": 0, "deleted_local": 0}
    for sub, make_key in (("documents", filestore.document_key), ("reports", filestore.report_key)):
        for path in sorted((root / sub).glob("*.pdf")):
            m = NAME.match(path.name)
            if not m:
                continue
            ident = m.group(1)
            data = path.read_bytes()
            key = make_key(ident)
            try:
                with session_scope() as s:
                    if sub == "documents":
                        doc = s.get(Document, uuid.UUID(hex=ident))
                        doc_id = doc.id if doc else None
                    else:
                        rep = s.get(Report, uuid.UUID(hex=ident))
                        doc_id = rep.document_id if rep else None
                    if doc_id is None:
                        out["skipped_no_record"] += 1
                        print(f"skipped (no database record): {sub}/{path.name}")
                        continue
                    present = s.scalar(select(FileObject.id).where(
                        FileObject.document_id == doc_id,
                        FileObject.file_type == (filestore.ORIGINAL if sub == "documents" else filestore.REPORT),
                        FileObject.checksum == hashlib.sha256(data).hexdigest(),
                    ))
                    if present is not None:
                        out["already_in_database"] += 1
                    else:
                        _, created = store.put(s, key, doc_id, (doc.filename if sub == "documents" else rep.filename), data)
                        out["copied"] += int(created)
                        if sub == "reports" and rep.storage_key is None:
                            rep.storage_key = key
                        if sub == "documents" and doc.storage_key is None:
                            doc.storage_key = key
                stored = store.read(key)  # fresh read from the database, checksum-verified by read()
                if stored is not None and hashlib.sha256(stored).hexdigest() == hashlib.sha256(data).hexdigest():
                    out["verified"] += 1
                    if delete_local:
                        path.unlink()
                        out["deleted_local"] += 1
                else:
                    out["failed"] += 1
                    print(f"NOT VERIFIED, local file kept: {sub}/{path.name}")
            except Exception as exc:  # keep going; the local file is untouched
                out["failed"] += 1
                print(f"failed ({type(exc).__name__}), local file kept: {sub}/{path.name}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(Path(__file__).resolve().parents[1] / "storage"), help="the old local storage folder")
    ap.add_argument("--delete-verified-local", action="store_true", help="remove each local file after its database copy is verified")
    args = ap.parse_args()
    root = Path(args.dir)
    if not root.exists():
        print(f"Nothing to migrate: {root} does not exist.")
        return 0
    result = migrate(root, args.delete_verified_local)
    print(result)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
