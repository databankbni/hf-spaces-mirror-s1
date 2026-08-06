import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional

import requests


class PortableOCRClient:
    def __init__(self, base_url: str, api_key: Optional[str] = None, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout = timeout

    def _headers(self, json_body: bool = False) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def health(self) -> Dict[str, Any]:
        res = requests.get(f"{self.base_url}/api/health", timeout=30)
        res.raise_for_status()
        return res.json()

    def upload(self, file_path: str) -> Dict[str, Any]:
        with open(file_path, "rb") as f:
            res = requests.post(
                f"{self.base_url}/api/upload",
                files={"file": f},
                headers=self._headers(),
                timeout=self.timeout,
            )
        res.raise_for_status()
        return res.json()

    def ocr_page(
        self,
        file_id: str,
        page: int,
        lang: str = "eng",
        psm: int = 3,
        region: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "file_id": file_id,
            "page": page,
            "lang": lang,
            "psm": psm,
        }
        if region:
            payload["region"] = region

        res = requests.post(
            f"{self.base_url}/api/ocr",
            headers=self._headers(json_body=True),
            data=json.dumps(payload),
            timeout=self.timeout,
        )
        res.raise_for_status()
        return res.json()

    def ocr_all(
        self,
        file_id: str,
        lang: str = "eng",
        psm: int = 3,
        start_page: int = 1,
        end_page: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "file_id": file_id,
            "lang": lang,
            "psm": psm,
            "start_page": start_page,
        }
        if end_page is not None:
            payload["end_page"] = end_page

        res = requests.post(
            f"{self.base_url}/api/ocr_all",
            headers=self._headers(json_body=True),
            data=json.dumps(payload),
            timeout=max(self.timeout, 300),
        )
        res.raise_for_status()
        return res.json()

    def download_searchable_pdf(
        self,
        file_id: str,
        output_path: str,
        lang: str = "eng",
        psm: int = 3,
    ) -> str:
        params = {"lang": lang, "psm": str(psm)}
        res = requests.get(
            f"{self.base_url}/api/download_ocr_pdf/{file_id}",
            headers=self._headers(),
            params=params,
            timeout=max(self.timeout, 600),
        )
        res.raise_for_status()

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(res.content)
        return str(out)

    def clear_session(self, file_id: str) -> Dict[str, Any]:
        payload = {"file_id": file_id}
        res = requests.post(
            f"{self.base_url}/api/clear_session",
            headers=self._headers(json_body=True),
            data=json.dumps(payload),
            timeout=60,
        )
        res.raise_for_status()
        return res.json()


def run_demo(args: argparse.Namespace) -> None:
    client = PortableOCRClient(args.base_url, api_key=args.api_key, timeout=args.timeout)

    print("Health:", client.health())

    meta = client.upload(args.file)
    print("Upload:", meta)

    file_id = meta["file_id"]

    first_page = client.ocr_page(file_id=file_id, page=1, lang=args.lang, psm=args.psm)
    print("\nFirst-page OCR:\n")
    print(first_page.get("text", ""))

    if args.extract_all and meta.get("file_type") == "pdf" and int(meta.get("pages", 1)) > 1:
        all_text = client.ocr_all(
            file_id=file_id,
            lang=args.lang,
            psm=args.psm,
            start_page=1,
            end_page=int(meta["pages"]),
        )
        print(f"\nExtracted pages: {len(all_text.get('results', []))}")

    if args.download_pdf:
        stem = Path(meta.get("filename", "ocr_output")).stem
        out_pdf = Path(args.output_dir) / f"{stem}_searchable_ocr.pdf"
        saved = client.download_searchable_pdf(file_id=file_id, output_path=str(out_pdf), lang=args.lang, psm=args.psm)
        print("Searchable PDF saved:", saved)

    if args.clear_session:
        cleared = client.clear_session(file_id)
        print("Session clear result:", cleared)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Portable OCR service client")
    p.add_argument("--base-url", required=True, help="Example: https://your-space-url")
    p.add_argument("--api-key", default="", help="OCR_API_PASSWORD value if auth is enabled")
    p.add_argument("--file", required=True, help="Path to input PDF/image")
    p.add_argument("--lang", default="eng", help="Tesseract language code")
    p.add_argument("--psm", type=int, default=3, help="Tesseract page segmentation mode")
    p.add_argument("--timeout", type=int, default=180, help="Request timeout in seconds")
    p.add_argument("--extract-all", action="store_true", help="Run OCR over all PDF pages")
    p.add_argument("--download-pdf", action="store_true", help="Download searchable OCR PDF")
    p.add_argument("--output-dir", default=".", help="Output directory for downloaded PDF")
    p.add_argument("--clear-session", action="store_true", help="Clear server session at the end")
    return p


if __name__ == "__main__":
    parser = build_parser()
    run_demo(parser.parse_args())
