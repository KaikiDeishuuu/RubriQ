from __future__ import annotations

import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.utils.files import ensure_pdf_suffix, sanitize_filename


@dataclass(slots=True)
class StorageObject:
    relative_path: str
    absolute_path: Path


class LocalStorageService:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> StorageObject:
        clean_relative = relative_path.lstrip("/")
        absolute_path = (self.root_dir / clean_relative).resolve()
        if not absolute_path.is_relative_to(self.root_dir.resolve()):
            raise ValueError("Storage path escapes storage root")
        return StorageObject(relative_path=clean_relative, absolute_path=absolute_path)

    def save_bytes(self, relative_path: str, data: bytes) -> StorageObject:
        storage_object = self._resolve(relative_path)
        storage_object.absolute_path.parent.mkdir(parents=True, exist_ok=True)
        storage_object.absolute_path.write_bytes(data)
        return storage_object

    def save_text(self, relative_path: str, content: str) -> StorageObject:
        return self.save_bytes(relative_path, content.encode("utf-8"))

    def read_bytes(self, relative_path: str) -> bytes:
        return self._resolve(relative_path).absolute_path.read_bytes()

    def read_text(self, relative_path: str) -> str:
        return self.read_bytes(relative_path).decode("utf-8")

    def delete(self, relative_path: str) -> None:
        storage_object = self._resolve(relative_path)
        if storage_object.absolute_path.exists():
            storage_object.absolute_path.unlink()

    def delete_tree(self, relative_path: str) -> None:
        storage_object = self._resolve(relative_path)
        if not storage_object.absolute_path.exists():
            return
        if storage_object.absolute_path.is_dir():
            shutil.rmtree(storage_object.absolute_path)
        else:
            storage_object.absolute_path.unlink()

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).absolute_path.exists()

    def path_for(self, relative_path: str) -> Path:
        return self._resolve(relative_path).absolute_path

    def relative_path_for(self, absolute_path: Path) -> str:
        return str(absolute_path.resolve().relative_to(self.root_dir.resolve()))

    def unique_pdf_path(self, scope: str, original_filename: str) -> str:
        safe_name = ensure_pdf_suffix(sanitize_filename(original_filename))
        unique_name = f"{uuid4().hex}_{safe_name}"
        scope_name = scope.strip("/")
        return f"{scope_name}/{unique_name}" if scope_name else unique_name

    def unique_file_path(self, scope: str, original_filename: str, suffix: str | None = None) -> str:
        safe_name = sanitize_filename(original_filename)
        if suffix:
            safe_name = f"{Path(safe_name).stem}{suffix}"
        unique_name = f"{uuid4().hex}_{safe_name}"
        scope_name = scope.strip("/")
        return f"{scope_name}/{unique_name}" if scope_name else unique_name


@lru_cache(maxsize=1)
def get_storage_service() -> LocalStorageService:
    return LocalStorageService(settings.storage_dir)

