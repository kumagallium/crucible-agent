"""LiteLLM config YAML の読み書き

モデルの追加・更新・削除を litellm_config.yaml に永続化する。
LiteLLM 再起動時に config からモデルがロードされるようにする。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# コンテナ内のマウントパス
CONFIG_PATH = Path("/app/litellm_config.yaml")


def _read() -> dict[str, Any]:
    """config YAML を読み込む"""
    if not CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(CONFIG_PATH.read_text()) or {}


def _write(data: dict[str, Any]) -> None:
    """config YAML を書き出す"""
    CONFIG_PATH.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def _get_model_list(data: dict[str, Any]) -> list[dict]:
    """model_list を取得（なければ作成）"""
    if "model_list" not in data or not isinstance(data["model_list"], list):
        data["model_list"] = []
    return data["model_list"]


def add_model(
    model_name: str,
    litellm_model: str,
    api_key: str,
    api_base: str | None = None,
) -> None:
    """モデルを config に追加する"""
    data = _read()
    model_list = _get_model_list(data)

    entry: dict[str, Any] = {
        "model_name": model_name,
        "litellm_params": {
            "model": litellm_model,
            "api_key": api_key,
        },
    }
    if api_base:
        entry["litellm_params"]["api_base"] = api_base

    model_list.append(entry)
    _write(data)
    logger.info("Config: added model '%s'", model_name)


def remove_model(model_name: str) -> None:
    """モデルを config から削除する"""
    data = _read()
    model_list = _get_model_list(data)

    original_len = len(model_list)
    data["model_list"] = [
        m for m in model_list if m.get("model_name") != model_name
    ]
    removed = original_len - len(data["model_list"])
    if removed:
        _write(data)
        logger.info("Config: removed model '%s'", model_name)


def update_model(
    old_name: str,
    model_name: str,
    litellm_model: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> None:
    """モデルを config で更新する

    api_key あり: エントリを丸ごと置換（完全更新）
    api_key なし: model_name のみ更新（軽量更新）
    """
    data = _read()
    model_list = _get_model_list(data)

    for m in model_list:
        if m.get("model_name") != old_name:
            continue

        if api_key and litellm_model:
            # 完全更新
            m["model_name"] = model_name
            m["litellm_params"] = {
                "model": litellm_model,
                "api_key": api_key,
            }
            if api_base:
                m["litellm_params"]["api_base"] = api_base
        else:
            # 軽量更新: 表示名のみ
            m["model_name"] = model_name

        _write(data)
        logger.info("Config: updated model '%s' -> '%s'", old_name, model_name)
        return

    # 見つからなかった場合（DB のみに存在していたモデル）
    if api_key and litellm_model:
        add_model(model_name, litellm_model, api_key, api_base)
