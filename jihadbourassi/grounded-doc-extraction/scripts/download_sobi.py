from __future__ import annotations

import argparse
import re
import urllib.error
import urllib.request
from pathlib import Path


SCAN_URL_TEMPLATE = (
    "https://api.bgs.ac.uk/"
    "sobi-scans/v1/borehole/scans/items/{bgs_id}"
)

DEFAULT_OUTPUT_DIR = Path("data/audit/pdfs")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download public BGS/SOBI borehole scan PDFs."
    )

    parser.add_argument(
        "bgs_ids",
        nargs="+",
        help="One or more BGS IDs to download.",
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Directory where PDFs are saved. "
            "Default: data/audit/pdfs"
        ),
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing PDF.",
    )

    return parser.parse_args()


def normalise_bgs_id(value):
    value = str(value).strip()

    if not value:
        raise ValueError("BGS ID cannot be empty.")

    try:
        return str(int(float(value)))
    except ValueError as exc:
        raise ValueError(
            f"Invalid BGS ID: {value!r}"
        ) from exc


def sanitise_filename(value):
    value = value.strip()

    value = re.sub(
        r'[<>:"/\\|?*]+',
        "-",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    value = value.strip(" .")

    if not value:
        return "scan.pdf"

    if not value.lower().endswith(".pdf"):
        value += ".pdf"

    return value


def filename_from_headers(headers, bgs_id):
    disposition = headers.get(
        "Content-Disposition",
        "",
    )

    match = re.search(
        r'filename="([^"]+)"',
        disposition,
        re.IGNORECASE,
    )

    if match:
        return sanitise_filename(
            match.group(1)
        )

    return f"{bgs_id}.pdf"


def download_pdf(
    bgs_id,
    output_dir,
    overwrite=False,
):
    url = SCAN_URL_TEMPLATE.format(
        bgs_id=bgs_id
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "grounded-doc-extraction-phase1"
            )
        },
    )

    print()
    print(f"BGS ID: {bgs_id}")
    print(f"URL: {url}")

    try:
        with urllib.request.urlopen(
            request,
            timeout=60,
        ) as response:
            status = response.status

            content_type = (
                response.headers.get_content_type()
            )

            filename = filename_from_headers(
                response.headers,
                bgs_id,
            )

            data = response.read()

    except urllib.error.HTTPError as exc:
        print(
            f"ERROR: HTTP {exc.code} "
            f"{exc.reason}"
        )
        return False

    except urllib.error.URLError as exc:
        print(
            f"ERROR: network failure: "
            f"{exc.reason}"
        )
        return False

    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: "
            f"{exc}"
        )
        return False

    print(f"status = {status}")
    print(f"content_type = {content_type}")
    print(f"bytes = {len(data)}")
    print(f"magic = {data[:5]!r}")

    if status != 200:
        print(
            "ERROR: response status is not 200."
        )
        return False

    if content_type != "application/pdf":
        print(
            "ERROR: response is not "
            "application/pdf."
        )
        return False

    if not data.startswith(b"%PDF-"):
        print(
            "ERROR: content does not start "
            "with the PDF signature %PDF-."
        )
        return False

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_dir / filename
    )

    if (
        output_path.exists()
        and not overwrite
    ):
        print(
            f"SKIP: already exists: "
            f"{output_path}"
        )
        return True

    output_path.write_bytes(data)

    print(
        f"saved = {output_path}"
    )

    return True


def main():
    args = parse_args()

    bgs_ids = [
        normalise_bgs_id(value)
        for value in args.bgs_ids
    ]

    successful = 0
    failed = 0

    for bgs_id in bgs_ids:
        ok = download_pdf(
            bgs_id=bgs_id,
            output_dir=args.output_dir,
            overwrite=args.overwrite,
        )

        if ok:
            successful += 1
        else:
            failed += 1

    print()
    print("SUMMARY")
    print(f"requested = {len(bgs_ids)}")
    print(f"successful = {successful}")
    print(f"failed = {failed}")


if __name__ == "__main__":
    main()