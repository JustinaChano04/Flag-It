"""Receipt storage: what is put can be got back, and keys can't escape the store."""

import os

import pytest

from flag_it.understand.receipts.store import LocalStore, MinioStore, store_from_env


def test_a_local_store_round_trips(tmp_path):
    store = LocalStore(tmp_path)
    store.put("receipts/t1/r1.pdf", b"%PDF-1.7 fake", "application/pdf")
    assert store.get("receipts/t1/r1.pdf") == b"%PDF-1.7 fake"


@pytest.mark.parametrize("key", ["../outside.pdf", "/etc/passwd", "receipts/../../x"])
def test_a_local_store_refuses_keys_outside_its_folder(tmp_path, key):
    with pytest.raises(ValueError, match="outside"):
        LocalStore(tmp_path).put(key, b"x", "application/pdf")


def test_without_minio_settings_the_store_is_a_local_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("FLAG_IT_MINIO_ENDPOINT", raising=False)
    monkeypatch.setenv("FLAG_IT_RECEIPT_DIR", str(tmp_path))
    store = store_from_env()
    assert isinstance(store, LocalStore) and store.root == tmp_path.resolve()


@pytest.mark.skipif(not os.environ.get("FLAG_IT_TEST_MINIO_ENDPOINT"), reason="set FLAG_IT_TEST_MINIO_ENDPOINT to test MinIO")
def test_minio_round_trips(monkeypatch):
    monkeypatch.setenv("FLAG_IT_MINIO_ENDPOINT", os.environ["FLAG_IT_TEST_MINIO_ENDPOINT"])
    monkeypatch.setenv("FLAG_IT_MINIO_BUCKET", "receipts-test")
    store = MinioStore.from_env()
    store.put("receipts/t1/r1.png", b"\x89PNG fake", "image/png")
    assert store.get("receipts/t1/r1.png") == b"\x89PNG fake"
