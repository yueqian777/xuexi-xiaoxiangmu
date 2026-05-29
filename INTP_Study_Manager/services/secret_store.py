from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime
from typing import Any

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    CRYPTOGRAPHY_AVAILABLE = True
except ModuleNotFoundError:
    InvalidTag = Exception
    AESGCM = None
    PBKDF2HMAC = None
    hashes = None
    CRYPTOGRAPHY_AVAILABLE = False

from db import DATA_DIR
from services.auth_service import require_login

SECRET_STORE_PATH = DATA_DIR / "api_keys.enc.json"
KDF_ITERATIONS = 390_000


def _secret_store_path(user_id: int | None = None) -> Any:
    if user_id is None:
        try:
            user_id = require_login().id
        except Exception:
            return SECRET_STORE_PATH
    return DATA_DIR / f"api_keys_user_{int(user_id)}.enc.json"


def _existing_secret_store_path(user_id: int | None = None) -> Any:
    store_path = _secret_store_path(user_id)
    if store_path.exists() or store_path == SECRET_STORE_PATH:
        return store_path
    if SECRET_STORE_PATH.exists() and _legacy_secret_store_visible_for_user(user_id):
        return SECRET_STORE_PATH
    return store_path


def _legacy_secret_store_visible_for_user(user_id: int | None = None) -> bool:
    try:
        payload = json.loads(SECRET_STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return _secret_store_owner_matches(payload.get("user_id"), user_id)


def _secret_store_owner_matches(owner_id: Any, user_id: int | None = None) -> bool:
    try:
        owner = int(owner_id or 0)
    except (TypeError, ValueError):
        return False
    if owner == 0:
        return True
    if user_id is None:
        try:
            user_id = require_login().id
        except Exception:
            return False
    return owner == int(user_id)


class SecretStoreError(RuntimeError):
    pass


def secret_store_exists() -> bool:
    return _existing_secret_store_path().exists()


def load_secret_store(master_password: str) -> dict[str, Any]:
    store_path = _existing_secret_store_path()
    if not store_path.exists():
        return {"providers": {}}
    if not master_password:
        raise SecretStoreError("请输入主密码。")
    _require_crypto()

    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
        if store_path == SECRET_STORE_PATH and not _secret_store_owner_matches(payload.get("user_id")):
            return {"providers": {}}
        salt = _b64decode(payload["salt"])
        nonce = _b64decode(payload["nonce"])
        ciphertext = _b64decode(payload["ciphertext"])
    except (OSError, KeyError, json.JSONDecodeError, ValueError) as exc:
        raise SecretStoreError("加密密钥库文件损坏或格式不正确。") from exc

    key = _derive_key(master_password, salt, int(payload.get("iterations", KDF_ITERATIONS)))
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise SecretStoreError("主密码不正确，无法解密 API Key。") from exc

    try:
        data = json.loads(plaintext.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise SecretStoreError("解密成功，但密钥库内容不是合法 JSON。") from exc
    if not isinstance(data, dict):
        raise SecretStoreError("密钥库内容格式不正确。")
    data.setdefault("providers", {})
    if store_path == SECRET_STORE_PATH and not _secret_store_owner_matches(data.get("user_id")):
        return {"providers": {}}
    _migrate_legacy_secret_store(master_password, data, store_path)
    return data


def save_secret_store(master_password: str, data: dict[str, Any]) -> None:
    if not master_password:
        raise SecretStoreError("请输入主密码。")
    _require_crypto()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    user = require_login()
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(master_password, salt, KDF_ITERATIONS)
    normalized = {
        "user_id": user.id,
        "providers": data.get("providers", {}),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    plaintext = json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    payload = {
        "version": 1,
        "algorithm": "AES-256-GCM",
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": KDF_ITERATIONS,
        "user_id": user.id,
        "salt": _b64encode(salt),
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
        "public_index": _build_public_index(normalized),
        "updated_at": normalized["updated_at"],
    }
    _secret_store_path(user.id).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_secret_public_index() -> list[dict[str, Any]]:
    store_path = _existing_secret_store_path()
    if not store_path.exists():
        return []
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    user = require_login()
    if int(payload.get("user_id") or 0) not in {0, user.id}:
        return []
    index = payload.get("public_index", {})
    providers = index.get("providers", [])
    return providers if isinstance(providers, list) else []


def _migrate_legacy_secret_store(master_password: str, data: dict[str, Any], source_path: Any) -> None:
    if source_path != SECRET_STORE_PATH:
        return
    try:
        user = require_login()
    except Exception:
        return
    user_path = _secret_store_path(user.id)
    if user_path.exists():
        return
    if not _secret_store_owner_matches(data.get("user_id"), user.id):
        return
    save_secret_store(master_password, data)


def upsert_provider_secret(
    data: dict[str, Any],
    *,
    provider_key: str,
    provider_name: str,
    api_key: str,
    model: str = "",
    provider_type: str = "",
    base_url: str = "",
) -> dict[str, Any]:
    key = api_key.strip()
    if not key:
        raise SecretStoreError("API Key 不能为空。")
    providers = dict(data.get("providers", {}))
    providers[str(provider_key)] = {
        "provider_key": provider_key,
        "provider_name": provider_name,
        "model": model,
        "provider_type": provider_type,
        "base_url": base_url,
        "api_key": key,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return {**data, "providers": providers}


def delete_provider_secret(data: dict[str, Any], provider_key: str) -> dict[str, Any]:
    providers = dict(data.get("providers", {}))
    providers.pop(str(provider_key), None)
    return {**data, "providers": providers}


def get_provider_secret(data: dict[str, Any], provider_key: str) -> str:
    item = data.get("providers", {}).get(str(provider_key), {})
    return str(item.get("api_key") or "")


def masked_secret(value: str) -> str:
    if not value:
        return "未保存"
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _build_public_index(data: dict[str, Any]) -> dict[str, Any]:
    providers = []
    for raw_key, item in data.get("providers", {}).items():
        if not isinstance(item, dict):
            continue
        providers.append(
            {
                "provider_key": str(item.get("provider_key") or raw_key),
                "provider_name": str(item.get("provider_name") or ""),
                "model": str(item.get("model") or ""),
                "provider_type": str(item.get("provider_type") or ""),
                "base_url": str(item.get("base_url") or ""),
                "updated_at": str(item.get("updated_at") or ""),
            }
        )
    return {"providers": providers}


def _derive_key(master_password: str, salt: bytes, iterations: int) -> bytes:
    _require_crypto()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(master_password.encode("utf-8"))


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _require_crypto() -> None:
    if CRYPTOGRAPHY_AVAILABLE:
        return
    raise SecretStoreError(
        "当前 Python 环境缺少 cryptography，无法使用加密 API Key 功能。"
        f"当前解释器：{sys.executable}。请运行：python -m pip install -r requirements.txt"
    )
