"""データセット fetch: ハッシュ不一致で失敗し、本文は git に入れない。"""

from __future__ import annotations

import csv
import io
import json
import subprocess
import zipfile
from pathlib import Path

import polars as pl
import pytest

from jev_prompts.data.fetch import (
    REMOTE_FILES,
    FetchError,
    HashMismatchError,
    UrllibTransport,
    fetch_datasets,
    load_task_records,
    source_id_from_case_id,
    verify_ledgers,
)
from jev_prompts.data.hashutil import content_hash
from jev_prompts.data.ledger import write_ledger

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeTransport:
    def __init__(
        self, files: dict[str, bytes], posts: dict[str, bytes] | None = None
    ) -> None:
        self.files = files
        self.posts = posts or {}
        self.gets: list[str] = []
        self.post_urls: list[str] = []

    def get(self, url: str) -> bytes:
        self.gets.append(url)
        try:
            return self.files[url]
        except KeyError as exc:
            raise FetchError(f"未スタブの GET: {url}") from exc

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> bytes:
        del body, headers
        self.post_urls.append(url)
        try:
            return self.posts[url]
        except KeyError as exc:
            raise FetchError(f"未スタブの POST: {url}") from exc


def _banking77_csv(*rows: tuple[str, str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", quotechar='"', quoting=csv.QUOTE_ALL)
    writer.writerow(["text", "category"])
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _parquet_bytes(df: pl.DataFrame) -> bytes:
    buffer = io.BytesIO()
    df.write_parquet(buffer)
    return buffer.getvalue()


def _esci_parquets() -> tuple[bytes, bytes]:
    examples = pl.DataFrame(
        {
            "example_id": [10, 11],
            "query": ["running shoes", "usb cable"],
            "product_id": ["p1", "p2"],
            "product_locale": ["us", "jp"],
            "esci_label": ["S", "E"],
        }
    )
    products = pl.DataFrame(
        {
            "product_id": ["p1", "p2"],
            "product_locale": ["us", "jp"],
            "product_title": ["Trail runner", "USB-C cable"],
            "product_description": ["Light trail shoe", "1m cable"],
        }
    )
    return _parquet_bytes(examples), _parquet_bytes(products)


def _sms_zip(*rows: tuple[str, str]) -> bytes:
    body = "".join(f"{label}\t{message}\n" for label, message in rows)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("smsSpamCollection/SMSSpamCollection", body)
        archive.writestr("readme", "test fixture")
    return buffer.getvalue()


def _url_ending(suffix: str) -> str:
    return next(item.url for item in REMOTE_FILES if item.url.endswith(suffix))


def _remote_payloads() -> dict[str, bytes]:
    examples, products = _esci_parquets()
    return {
        _url_ending("train.csv"): _banking77_csv(
            ("I want my card", "card_arrival"),
            ("What is the fee", "transaction_fee_charged"),
        ),
        _url_ending("test.csv"): _banking77_csv(("Where is my card", "card_arrival")),
        _url_ending("examples.parquet"): examples,
        _url_ending("products.parquet"): products,
        _url_ending("sms+spam+collection.zip"): _sms_zip(
            ("ham", "see you at 7"),
            ("spam", "WIN a prize now"),
        ),
    }


def _ledger_row(
    *,
    case_id: str,
    task: str,
    content_hash_value: str,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "task": task,
        "split": "dev",
        "gold": "x",
        "content_hash": content_hash_value,
        "extract_seed": 20260921,
        "stratum": "random",
    }


def test_hash_mismatch_fails(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    cases_root = tmp_path / "cases"
    fetch_datasets(raw_root, transport=FakeTransport(_remote_payloads()))
    write_ledger(
        pl.DataFrame(
            [
                _ledger_row(
                    case_id="choice:test:0",
                    task="choice",
                    content_hash_value="0" * 64,
                )
            ]
        ),
        cases_root / "choice.jsonl",
    )
    with pytest.raises(HashMismatchError, match="ハッシュ不一致"):
        verify_ledgers(raw_root, cases_root)


def test_matching_hashes_pass(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    cases_root = tmp_path / "cases"
    fetch_datasets(raw_root, transport=FakeTransport(_remote_payloads()))
    choice = load_task_records(raw_root, "choice")
    score = load_task_records(raw_root, "score")
    noul = load_task_records(raw_root, "noul")
    write_ledger(
        pl.DataFrame(
            [
                _ledger_row(
                    case_id="choice:test:0",
                    task="choice",
                    content_hash_value=content_hash("choice", choice["test:0"]),
                )
            ]
        ),
        cases_root / "choice.jsonl",
    )
    write_ledger(
        pl.DataFrame(
            [
                _ledger_row(
                    case_id="score:10",
                    task="score",
                    content_hash_value=content_hash("score", score["10"]),
                )
            ]
        ),
        cases_root / "score.jsonl",
    )
    write_ledger(
        pl.DataFrame(
            [
                _ledger_row(
                    case_id="noul:0",
                    task="noul",
                    content_hash_value=content_hash("noul", noul["0"]),
                )
            ]
        ),
        cases_root / "noul.jsonl",
    )
    assert verify_ledgers(raw_root, cases_root) == 3


def test_missing_raw_case_fails(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    cases_root = tmp_path / "cases"
    fetch_datasets(raw_root, transport=FakeTransport(_remote_payloads()))
    write_ledger(
        pl.DataFrame(
            [
                _ledger_row(
                    case_id="choice:missing:99",
                    task="choice",
                    content_hash_value="a" * 64,
                )
            ]
        ),
        cases_root / "choice.jsonl",
    )
    with pytest.raises(HashMismatchError, match="raw にケースが無い"):
        verify_ledgers(raw_root, cases_root)


def test_verify_without_ledger_is_noop(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    fetch_datasets(raw_root, transport=FakeTransport(_remote_payloads()))
    assert verify_ledgers(raw_root, tmp_path / "cases") == 0


def test_esci_index_is_english_us_only(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    fetch_datasets(raw_root, transport=FakeTransport(_remote_payloads()))
    records = load_task_records(raw_root, "score")
    assert set(records) == {"10"}
    assert records["10"]["title"] == "Trail runner"
    assert "11" not in records


def test_fetch_writes_unpacked_raw(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    transport = FakeTransport(_remote_payloads())
    fetch_datasets(raw_root, transport=transport)
    assert (raw_root / "banking77" / "train.csv").is_file()
    assert (raw_root / "banking77" / "test.csv").is_file()
    assert (raw_root / "esci" / "shopping_queries_dataset_examples.parquet").is_file()
    assert (raw_root / "sms_spam" / "SMSSpamCollection").is_file()
    assert not list(raw_root.glob("**/*.zip"))
    assert transport.gets


def test_lfs_pointer_is_resolved(tmp_path: Path) -> None:
    payloads = _remote_payloads()
    examples_url = _url_ending("examples.parquet")
    payloads[examples_url] = (
        "version https://git-lfs.github.com/spec/v1\n"
        "oid sha256:" + ("a" * 64) + "\n"
        "size 4\n"
    ).encode("utf-8")
    href = "https://objects.githubusercontent.com/esci-examples"
    payloads[href] = _esci_parquets()[0]
    lfs_batch = "https://github.com/amazon-science/esci-data.git/info/lfs/objects/batch"
    transport = FakeTransport(
        payloads,
        {
            lfs_batch: json.dumps(
                {"objects": [{"actions": {"download": {"href": href}}}]}
            ).encode("utf-8")
        },
    )
    fetch_datasets(tmp_path / "raw", transport=transport)
    assert lfs_batch in transport.post_urls
    assert href in transport.gets
    records = load_task_records(tmp_path / "raw", "score")
    assert records["10"]["query"] == "running shoes"


def test_git_ignores_data_raw_bodies() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "data/raw/" in gitignore
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", "data/raw/banking77/train.csv"],
        cwd=REPO_ROOT,
        check=False,
    )
    assert ignored.returncode == 0


def test_readme_documents_fetch_steps() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "本文は同梱しない" in readme
    assert "scripts/fetch_data.py" in readme
    assert "data/raw/" in readme
    assert "ハッシュ" in readme


def test_source_urls_are_documented_distributors() -> None:
    urls = " ".join(item.url for item in REMOTE_FILES)
    assert "PolyAI-LDN/task-specific-datasets" in urls
    assert "amazon-science/esci-data" in urls
    assert "archive.ics.uci.edu" in urls


def test_source_id_from_case_id_keeps_split() -> None:
    assert source_id_from_case_id("choice:test:0") == "test:0"
    assert source_id_from_case_id("score:10") == "10"


def test_fetch_script_exists() -> None:
    script = (REPO_ROOT / "scripts" / "fetch_data.py").read_text(encoding="utf-8")
    assert "fetch_and_verify" in script
    assert "typer" in script


def test_default_transport_is_urllib() -> None:
    assert UrllibTransport().timeout_s == 600
