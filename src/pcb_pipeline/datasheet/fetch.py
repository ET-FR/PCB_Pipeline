"""Download the datasheets of the selected parts into datasheets/ and keep an index.

The PDFs stay local (size, copyright); datasheets/index.yaml is committed. When a
download fails (site blocks robots, login, no URL), the part is listed as missing so
the user can drop the PDF in by hand; the next run registers it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import yaml

USER_AGENT = "pcb-pipeline/0.1 (datasheet fetch)"


def datasheet_filename(mpn: str, revision: str | None) -> str:
    safe = lambda s: re.sub(r"[^A-Za-z0-9._+-]", "-", s)
    return f"{safe(mpn)}@{safe(revision or 'unknown')}.pdf"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class FetchResult:
    present: list[str] = field(default_factory=list)      # already on disk
    downloaded: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)      # file hash differs from the index
    missing: list[dict] = field(default_factory=list)     # {mpn, file, url, reason}


def _download(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 (URLs come from the spec)
        return resp.read()


def load_index(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return data if isinstance(data, dict) and isinstance(data.get("datasheets"), list) else {"datasheets": []}


def fetch_datasheets(spec: dict, folder: Path, timeout: float = 30.0, offline: bool = False) -> FetchResult:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    index_path = folder / "index.yaml"
    index = load_index(index_path)
    entries = {e["mpn"]: e for e in index["datasheets"]}
    result = FetchResult()
    today = dt.date.today().isoformat()

    for part in spec.get("parts", []):
        if part.get("status") != "selected":
            continue
        mpn = part["mpn"]
        ds = part.get("datasheet", {})
        name = ds.get("file") or datasheet_filename(mpn, ds.get("revision"))
        name = Path(name).name
        path = folder / name
        url = ds.get("url")

        if not path.exists():
            if offline or not url:
                result.missing.append({"mpn": mpn, "file": name, "url": url,
                                       "reason": "offline" if url else "no URL in the spec"})
                continue
            try:
                data = _download(url, timeout)
            except Exception as exc:  # network errors, HTTP errors, blocked hosts
                result.missing.append({"mpn": mpn, "file": name, "url": url, "reason": f"download failed: {exc}"})
                continue
            if not data.startswith(b"%PDF"):
                result.missing.append({"mpn": mpn, "file": name, "url": url,
                                       "reason": "the URL did not return a PDF (login page or HTML viewer?)"})
                continue
            path.write_bytes(data)
            result.downloaded.append(mpn)
        else:
            result.present.append(mpn)

        digest = sha256(path)
        old = entries.get(mpn)
        if old and old.get("sha256") and old["sha256"] != digest:
            result.changed.append(mpn)
        entries[mpn] = {
            "mpn": mpn,
            "manufacturer": part.get("manufacturer", old.get("manufacturer", "") if old else ""),
            "revision": ds.get("revision", old.get("revision", "") if old else ""),
            "url": url or (old or {}).get("url", ""),
            "file": name,
            "sha256": digest,
            "registered": old["registered"] if old and old.get("sha256") == digest and old.get("registered") else today,
        }

    index["datasheets"] = sorted(entries.values(), key=lambda e: e["mpn"])
    header = ("# One entry per datasheet. The PDFs stay local; this index is committed.\n"
              "# Written by `pcb-pipeline fetch-datasheets`.\n")
    index_path.write_text(header + yaml.safe_dump(index, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return result
