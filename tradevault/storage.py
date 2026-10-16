from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import requests
from flask import current_app


class StorageUnavailable(RuntimeError):
    pass


def _platform_config() -> tuple[str, str] | None:
    if current_app.config.get("FORCE_LOCAL_STORAGE_FOR_TESTS") and current_app.testing:
        return None
    base = os.getenv("MANUS_API_URL", "").rstrip("/")
    key = os.getenv("MANUS_API_KEY", "")
    return (base, key) if base and key else None


def _local_mode() -> bool:
    return current_app.config["TRADEVAULT_ENV"] != "production" and current_app.config["LOCAL_STORAGE_ENABLED"]


def new_key(user_id: int, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".img"
    return f"tradevault/{user_id}/{uuid.uuid4().hex}{suffix}"


def put_object(key: str, data: bytes, content_type: str) -> None:
    platform = _platform_config()
    if platform:
        base, api_key = platform
        response = requests.get(f"{base}/v1/storage/presign/put", params={"path": key}, headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
        response.raise_for_status()
        url = response.json().get("url")
        if not url:
            raise StorageUnavailable("Object storage did not return an upload URL.")
        uploaded = requests.put(url, data=data, headers={"Content-Type": content_type}, timeout=120)
        uploaded.raise_for_status()
        return
    if not _local_mode():
        raise StorageUnavailable("Durable project storage is unavailable. Configure the platform storage runtime before accepting uploads.")
    root = Path(current_app.config["LOCAL_UPLOAD_FOLDER"]).resolve()
    destination = (root / key).resolve()
    if root not in destination.parents:
        raise StorageUnavailable("Invalid storage key.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def get_object_url(key: str) -> str | None:
    platform = _platform_config()
    if platform:
        base, api_key = platform
        response = requests.get(f"{base}/v1/storage/presign/get", params={"path": key}, headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
        response.raise_for_status()
        url = response.json().get("url")
        if not url:
            raise StorageUnavailable("Object storage did not return a download URL.")
        return url
    if not _local_mode():
        raise StorageUnavailable("Durable project storage is unavailable.")
    return None


def read_object(key: str) -> bytes:
    url = get_object_url(key)
    if url:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.content
    root = Path(current_app.config["LOCAL_UPLOAD_FOLDER"]).resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise StorageUnavailable("Invalid storage key.")
    return path.read_bytes()


def delete_local_object(key: str) -> None:
    if not _local_mode():
        return
    root = Path(current_app.config["LOCAL_UPLOAD_FOLDER"]).resolve()
    path = (root / key).resolve()
    if root in path.parents and path.exists():
        path.unlink()
