import asyncio
import argparse
import json
import sys
import time
from pathlib import Path

import requests
from sqlalchemy import select

sys.path.insert(0, ".")

from backend.app.core.database import async_session_factory  # noqa: E402
from backend.app.core.tenant_context import set_tenant_context  # noqa: E402
from backend.app.models.raw import Document, RawParse  # noqa: E402

BASE_URL = "http://localhost:8000/api/v1"
EMAIL = "admin@test.com"
PASSWORD = "PZAD-QyiIWCBct2iRxvEkQ"
DOC_TYPE = "CONTRACT"
POLL_SECONDS = 3
TIMEOUT_SECONDS = 1800
READ_TIMEOUT_SECONDS = 300


def _select_test_pdf(selected_path: str | None) -> Path:
    if selected_path:
        path = Path(selected_path)
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    demo_dir = Path("data/demo")
    candidates = sorted(demo_dir.glob("Sample Contract *.pdf"))
    if not candidates:
        raise FileNotFoundError(f"No scanned PDF contracts found in {demo_dir}")
    return candidates[0]


def _authenticate() -> tuple[str, str]:
    response = requests.post(
        f"{BASE_URL}/auth/token",
        json={
            "email": EMAIL,
            "password": PASSWORD,
            "tenant_name": "Default Tenant",
        },
        timeout=READ_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["access_token"], payload["user"]["tenant_id"]


def _upload_file(token: str, file_path: Path) -> str:
    with file_path.open("rb") as handle:
        response = requests.post(
            f"{BASE_URL}/ingest/upload",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (file_path.name, handle, "application/pdf")},
            data={"doc_type": DOC_TYPE},
            timeout=READ_TIMEOUT_SECONDS,
        )
    response.raise_for_status()
    payload = response.json()
    print("Upload response:")
    print(json.dumps(payload, indent=2))
    return payload["document_id"]


async def _fetch_document_status(document_id: str, tenant_id: str) -> dict:
    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_id)
        doc_stmt = select(Document).where(Document.id == document_id)
        doc = (await db.execute(doc_stmt)).scalar_one_or_none()
        if doc is None:
            raise RuntimeError(f"Document {document_id} not found in database")
        return {
            "document_id": str(doc.id),
            "filename": doc.original_filename,
            "doc_type": str(doc.doc_type),
            "file_size": doc.file_size,
            "parse_status": str(doc.parse_status),
            "created_at": str(doc.created_at) if doc.created_at else None,
            "low_confidence_flag": bool(doc.low_confidence_flag),
        }


async def _poll_until_complete(document_id: str, tenant_id: str) -> dict:
    started = time.time()
    while True:
        status_payload = await _fetch_document_status(document_id, tenant_id)
        status_value = status_payload.get("parse_status")
        print(
            f"[poll] status={status_value} "
            f"filename={status_payload.get('filename')} "
            f"created_at={status_payload.get('created_at')}"
        )
        if status_value != "PENDING":
            return status_payload
        if time.time() - started > TIMEOUT_SECONDS:
            raise TimeoutError(f"Timed out waiting for document {document_id} to finish parsing")
        time.sleep(POLL_SECONDS)


async def _inspect_raw_parse(document_id: str, tenant_id: str) -> dict:
    async with async_session_factory() as db:
        await set_tenant_context(db, tenant_id)

        doc_stmt = select(Document).where(Document.id == document_id)
        doc = (await db.execute(doc_stmt)).scalar_one_or_none()

        raw_stmt = (
            select(RawParse)
            .where(RawParse.document_id == document_id)
            .order_by(RawParse.raw_version.desc())
        )
        raw_parse = (await db.execute(raw_stmt)).scalars().first()

        print("\nDatabase document row:")
        if doc is None:
            print("  not found")
        else:
            print(
                json.dumps(
                    {
                        "document_id": str(doc.id),
                        "parse_status": str(doc.parse_status),
                        "low_confidence_flag": bool(doc.low_confidence_flag),
                        "file_path": doc.file_path,
                        "original_filename": doc.original_filename,
                    },
                    indent=2,
                )
            )

        print("\nLatest raw_parses row:")
        if raw_parse is None:
            print("  not found")
            return {
                "raw_parse_id": None,
                "parse_confidence": None,
                "failure_flags": [],
                "line_items_count": None,
            }

        structured = raw_parse.structured_output_jsonb or {}
        failure_flags = raw_parse.failure_flags or []
        payload = {
            "raw_parse_id": str(raw_parse.id),
            "raw_version": raw_parse.raw_version,
            "parser_used": raw_parse.parser_used,
            "parse_confidence": raw_parse.parse_confidence,
            "failure_flags": failure_flags,
            "structured_output_excerpt": {
                "parser_used": structured.get("parser_used"),
                "parse_confidence": structured.get("parse_confidence"),
                "failure_flags": structured.get("failure_flags"),
                "header": structured.get("header"),
                "line_items_count": len(structured.get("line_items", [])),
                "raw_extracted_data_keys": sorted((structured.get("raw_extracted_data") or {}).keys()),
                "raw_error": (structured.get("raw_extracted_data") or {}).get("error"),
            },
        }
        print(json.dumps(payload, indent=2))
        return {
            "raw_parse_id": payload["raw_parse_id"],
            "parse_confidence": payload["parse_confidence"],
            "failure_flags": payload["failure_flags"],
            "line_items_count": payload["structured_output_excerpt"]["line_items_count"],
        }


async def _main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file_path", nargs="?", help="Optional scanned PDF path")
    args = parser.parse_args()

    file_path = _select_test_pdf(args.file_path)
    print(f"Using scanned PDF: {file_path}")

    token, tenant_id = _authenticate()
    print(f"Authenticated tenant_id={tenant_id}")

    document_id = _upload_file(token, file_path)
    print(f"Uploaded document_id={document_id}")

    final_status = await _poll_until_complete(document_id, tenant_id)
    print("\nFinal API status:")
    print(json.dumps(final_status, indent=2))

    raw_parse_summary = await _inspect_raw_parse(document_id, tenant_id)
    print("\nSummary:")
    print(
        json.dumps(
            {
                "filename": file_path.name,
                "document_id": document_id,
                "final_status": final_status.get("parse_status"),
                "parse_confidence": raw_parse_summary.get("parse_confidence"),
                "failure_flags": raw_parse_summary.get("failure_flags"),
                "item_count": raw_parse_summary.get("line_items_count"),
            },
            indent=2,
        )
    )


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
