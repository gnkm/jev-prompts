"""配布元から data/raw へ取得し、台帳の content_hash と照合する。

実験ランナーは配布元に触れない。HTTP は fetch コマンドだけが行う。
"""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import polars as pl

from jev_prompts.data.hashutil import content_hash
from jev_prompts.data.ledger import read_ledger
from jev_prompts.data.schema import TASKS, TaskId

USER_AGENT = "jev-prompts-fetch/0.1"
LFS_POINTER_PREFIX = "version https://git-lfs.github.com/spec/v1"
SMS_COLLECTION_NAME = "smsspamcollection"


class FetchError(ValueError):
    """取得または展開に失敗した。"""


class HashMismatchError(FetchError):
    """台帳の content_hash と raw 本文が一致しない。"""


class Transport(Protocol):
    def get(self, url: str) -> bytes: ...

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> bytes: ...


class UrllibTransport:
    timeout_s = 600

    def get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        return _read_url(request, timeout_s=self.timeout_s)

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        merged = {"User-Agent": USER_AGENT, **headers}
        request = urllib.request.Request(url, data=body, headers=merged, method="POST")
        return _read_url(request, timeout_s=self.timeout_s)


def _read_url(request: urllib.request.Request, *, timeout_s: float) -> bytes:
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"取得失敗 {request.full_url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"取得失敗 {request.full_url}: {exc.reason}") from exc


@dataclass(frozen=True, slots=True)
class RemoteFile:
    url: str
    relative_path: str
    kind: Literal["file", "zip"]
    lfs_repo: str | None = None


REMOTE_FILES: tuple[RemoteFile, ...] = (
    RemoteFile(
        url=(
            "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
            "master/banking_data/train.csv"
        ),
        relative_path="banking77/train.csv",
        kind="file",
    ),
    RemoteFile(
        url=(
            "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/"
            "master/banking_data/test.csv"
        ),
        relative_path="banking77/test.csv",
        kind="file",
    ),
    RemoteFile(
        url=(
            "https://github.com/amazon-science/esci-data/raw/main/"
            "shopping_queries_dataset/shopping_queries_dataset_examples.parquet"
        ),
        relative_path="esci/shopping_queries_dataset_examples.parquet",
        kind="file",
        lfs_repo="amazon-science/esci-data",
    ),
    RemoteFile(
        url=(
            "https://github.com/amazon-science/esci-data/raw/main/"
            "shopping_queries_dataset/shopping_queries_dataset_products.parquet"
        ),
        relative_path="esci/shopping_queries_dataset_products.parquet",
        kind="file",
        lfs_repo="amazon-science/esci-data",
    ),
    RemoteFile(
        url="https://archive.ics.uci.edu/static/public/228/sms+spam+collection.zip",
        relative_path="sms_spam",
        kind="zip",
    ),
)

_TASK_DIRS: dict[TaskId, str] = {
    "choice": "banking77",
    "score": "esci",
    "noul": "sms_spam",
}


def source_id_from_case_id(case_id: str) -> str:
    _task, sep, rest = case_id.partition(":")
    if not sep or not rest:
        raise FetchError(f"case_id が task:source_id 形式ではない: {case_id}")
    return rest


def fetch_datasets(raw_root: Path, *, transport: Transport | None = None) -> list[Path]:
    """3 データセットを data/raw 相当へ展開する。"""
    client = transport or UrllibTransport()
    raw_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for remote in REMOTE_FILES:
        dest = raw_root / remote.relative_path
        payload = _download(client, remote)
        if remote.kind == "zip":
            dest.mkdir(parents=True, exist_ok=True)
            _extract_zip(payload, dest)
            written.append(dest)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        written.append(dest)
    return written


def verify_ledgers(raw_root: Path, cases_root: Path) -> int:
    """台帳の各行について raw 本文ハッシュを照合する。不一致・台帳なしは失敗する。"""
    ledgers = sorted(cases_root.glob("*.jsonl"))
    if not ledgers:
        raise FetchError(f"照合する台帳が無い: {cases_root}")
    cache: dict[TaskId, dict[str, dict[str, Any]]] = {}
    checked = 0
    for path in ledgers:
        if path.stat().st_size == 0:
            raise FetchError(f"台帳が空: {path}")
        df = read_ledger(path)
        if df.height == 0:
            raise FetchError(f"台帳が空: {path}")
        for row in df.to_dicts():
            task = _require_task(str(row["task"]))
            if task not in cache:
                cache[task] = load_task_records(raw_root, task)
            source_id = source_id_from_case_id(str(row["case_id"]))
            record = cache[task].get(source_id)
            if record is None:
                raise HashMismatchError(f"raw にケースが無い: {row['case_id']}")
            actual = content_hash(task, record)
            expected = str(row["content_hash"])
            if actual != expected:
                raise HashMismatchError(f"ハッシュ不一致: {row['case_id']}")
            checked += 1
    if checked == 0:
        raise FetchError(f"照合できたケースが無い: {cases_root}")
    return checked


def fetch_and_verify(
    raw_root: Path,
    cases_root: Path,
    *,
    transport: Transport | None = None,
) -> int:
    fetch_datasets(raw_root, transport=transport)
    return verify_ledgers(raw_root, cases_root)


def load_task_records(raw_root: Path, task: TaskId) -> dict[str, dict[str, Any]]:
    directory = raw_root / _TASK_DIRS[task]
    if task == "choice":
        return load_banking77(directory)
    if task == "score":
        return load_esci(directory)
    return load_sms_spam(directory)


def load_banking77(directory: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for split, filename in (("train", "train.csv"), ("test", "test.csv")):
        path = directory / filename
        _require_file(path)
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(
                handle,
                delimiter=",",
                quotechar='"',
                quoting=csv.QUOTE_ALL,
                skipinitialspace=True,
            )
            header = [cell.strip() for cell in next(reader)]
            try:
                text_index = header.index("text")
            except ValueError as exc:
                raise FetchError(f"BANKING77 に text 列が無い: {path}") from exc
            gold_index = header.index("category") if "category" in header else None
            for index, row in enumerate(reader):
                if not row:
                    continue
                source_id = f"{split}:{index}"
                record: dict[str, Any] = {
                    "source_id": source_id,
                    "text": row[text_index],
                }
                if gold_index is not None and gold_index < len(row) and row[gold_index]:
                    record["gold"] = row[gold_index]
                records[source_id] = record
    if not records:
        raise FetchError(f"BANKING77 が空: {directory}")
    return records


def load_esci(directory: Path) -> dict[str, dict[str, Any]]:
    examples_path = directory / "shopping_queries_dataset_examples.parquet"
    products_path = directory / "shopping_queries_dataset_products.parquet"
    _require_file(examples_path)
    _require_file(products_path)
    examples = pl.read_parquet(examples_path)
    products = pl.read_parquet(products_path)
    missing_ex = {"example_id", "query", "product_id", "product_locale"} - set(
        examples.columns
    )
    missing_pr = {"product_id", "product_locale", "product_title"} - set(
        products.columns
    )
    if missing_ex:
        raise FetchError(f"ESCI examples の列が不足: {sorted(missing_ex)}")
    if missing_pr:
        raise FetchError(f"ESCI products の列が不足: {sorted(missing_pr)}")
    examples = examples.filter(pl.col("product_locale") == "us")
    products = products.filter(pl.col("product_locale") == "us")
    product_cols = ["product_id", "product_locale", "product_title"]
    if "product_description" in products.columns:
        product_cols.append("product_description")
    joined = examples.join(
        products.select(product_cols),
        on=["product_id", "product_locale"],
        how="left",
    )
    records: dict[str, dict[str, Any]] = {}
    for row in joined.to_dicts():
        source_id = str(row["example_id"])
        description = row.get("product_description")
        title = row.get("product_title")
        record: dict[str, Any] = {
            "source_id": source_id,
            "query": row["query"],
            "title": "" if title is None else str(title),
            "description": "" if description is None else str(description),
        }
        label = row.get("esci_label")
        if label is not None and str(label):
            record["gold"] = label
        records[source_id] = record
    if not records:
        raise FetchError(f"ESCI の英語（us）行が空: {directory}")
    return records


def load_sms_spam(directory: Path) -> dict[str, dict[str, Any]]:
    path = _sms_collection_path(directory)
    records: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(_read_text(path).splitlines()):
        if not line.strip():
            continue
        _label, sep, message = line.partition("\t")
        if not sep:
            raise FetchError(f"SMS 行がタブ区切りではない: {index}")
        source_id = str(index)
        records[source_id] = {
            "source_id": source_id,
            "message": message,
            "gold": _label.strip(),
        }
    if not records:
        raise FetchError(f"SMS Spam が空: {path}")
    return records


def _download(transport: Transport, remote: RemoteFile) -> bytes:
    payload = transport.get(remote.url)
    if not _is_lfs_pointer(payload):
        return payload
    repo = remote.lfs_repo or _lfs_repo_from_url(remote.url)
    oid, size = _parse_lfs_pointer(payload)
    href = _lfs_download_href(transport, repo, oid, size)
    blob = transport.get(href)
    if _is_lfs_pointer(blob):
        raise FetchError(f"Git LFS の本体が取れない: {remote.url}")
    return blob


def _is_lfs_pointer(payload: bytes) -> bool:
    if len(payload) > 1024:
        return False
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return text.startswith(LFS_POINTER_PREFIX)


def _parse_lfs_pointer(payload: bytes) -> tuple[str, int]:
    oid: str | None = None
    size: int | None = None
    for line in payload.decode("utf-8").splitlines():
        if line.startswith("oid sha256:"):
            oid = line.removeprefix("oid sha256:").strip()
        elif line.startswith("size "):
            size = int(line.split(None, 1)[1])
    if not oid or size is None:
        raise FetchError("Git LFS ポインタが不正")
    return oid, size


def _lfs_repo_from_url(url: str) -> str:
    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) < 2:
        raise FetchError(f"LFS のリポジトリを URL から読めない: {url}")
    return f"{parts[0]}/{parts[1]}"


def _lfs_download_href(transport: Transport, repo: str, oid: str, size: int) -> str:
    endpoint = f"https://github.com/{repo}.git/info/lfs/objects/batch"
    body = json.dumps(
        {
            "operation": "download",
            "transfers": ["basic"],
            "objects": [{"oid": oid, "size": size}],
        }
    ).encode("utf-8")
    headers = {
        "Accept": "application/vnd.git-lfs+json",
        "Content-Type": "application/vnd.git-lfs+json",
    }
    raw = transport.post(endpoint, body, headers)
    try:
        payload = json.loads(raw.decode("utf-8"))
        href = payload["objects"][0]["actions"]["download"]["href"]
    except (IndexError, KeyError, ValueError, UnicodeDecodeError) as exc:
        raise FetchError(f"Git LFS の応答が不正: {repo}") from exc
    if not isinstance(href, str) or not href:
        raise FetchError(f"Git LFS の download URL が空: {repo}")
    return href


def _extract_zip(payload: bytes, dest: Path) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise FetchError("ZIP が壊れている") from exc
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    found_collection = False
    with archive:
        for info in archive.infolist():
            name = Path(info.filename).name
            if not name or info.is_dir():
                continue
            target = (dest / name).resolve()
            if not target.is_relative_to(dest_resolved):
                raise FetchError(f"ZIP に危険なパスがある: {info.filename}")
            target.write_bytes(archive.read(info))
            if name.lower() == SMS_COLLECTION_NAME:
                found_collection = True
    if not found_collection:
        raise FetchError("ZIP に SMSSpamCollection が無い")


def _sms_collection_path(directory: Path) -> Path:
    if not directory.is_dir():
        raise FetchError(f"SMS の展開先が無い: {directory}")
    matches = [
        path
        for path in directory.iterdir()
        if path.is_file() and path.name.lower() == SMS_COLLECTION_NAME
    ]
    if not matches:
        raise FetchError(f"SMSSpamCollection が無い: {directory}")
    return matches[0]


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise FetchError(f"raw ファイルが無い: {path}")


def _require_task(task: str) -> TaskId:
    if task not in TASKS:
        raise FetchError(f"未知の課題: {task}")
    return task
