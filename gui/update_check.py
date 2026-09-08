# -*- coding: utf-8 -*-
"""Best yolo 更新检查的纯网络与版本逻辑，不依赖 Qt。"""
from __future__ import annotations

import json
import re
import ssl
from urllib.parse import quote
from urllib.request import (HTTPSHandler, ProxyHandler, Request, build_opener)

from appmeta import (APP_VERSION, GITHUB_LATEST_API, GITHUB_RELEASES_URL,
                     GITHUB_REPOSITORY)


NO_NETWORK_MESSAGE = "没有网络，暂时无法检测更新。"
MAX_RESPONSE_BYTES = 1024 * 1024
_VERSION_RE = re.compile(
    r"^[vV]?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.-]+))?$"
)


def version_key(value):
    """把 v1.2.3 变成可比较元组；非法版本返回 None。"""
    match = _VERSION_RE.fullmatch((value or "").strip())
    if not match:
        return None
    major, minor, patch = (int(match.group(i)) for i in range(1, 4))
    suffix = match.group(4)
    return major, minor, patch, 1 if suffix is None else 0


def is_newer(latest, current=APP_VERSION):
    latest_key, current_key = version_key(latest), version_key(current)
    return bool(latest_key and current_key and latest_key > current_key)


def parse_release(payload, current=APP_VERSION):
    """校验 GitHub latest release 响应并生成界面使用的数据。"""
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise ValueError("GitHub 没有返回稳定版本")
    tag = str(payload.get("tag_name") or "").strip()
    key = version_key(tag)
    if key is None:
        raise ValueError("GitHub 返回了无法识别的版本号")
    normalized = ".".join(str(x) for x in key[:3])
    body = str(payload.get("body") or "").strip()
    if len(body) > 100_000:
        body = body[:100_000] + "\n\n（更新说明过长，已截断）"
    return {
        "tag": tag,
        "version": normalized,
        "title": str(payload.get("name") or tag).strip(),
        "body": body,
        "published_at": str(payload.get("published_at") or "").strip(),
        "url": f"{GITHUB_RELEASES_URL}/tag/{quote(tag, safe='')}",
        "update_available": is_newer(tag, current),
    }


def _https_opener():
    """使用 certifi CA，并保留系统/环境代理（Clash 等需要它）。"""
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    return build_opener(ProxyHandler(), HTTPSHandler(context=context))


def _load_latest_json(timeout=5.0, opener=None):
    opener = opener or _https_opener()
    request = Request(
        GITHUB_LATEST_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"BestYolo/{APP_VERSION}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with opener.open(request, timeout=float(timeout)) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("GitHub 响应过大")
    return json.loads(raw.decode("utf-8"))


def check_for_update(current=APP_VERSION, timeout=5.0, loader=None):
    """返回 (release, error)。任何网络/格式错误都转成安静的中文错误。"""
    try:
        payload = (loader or _load_latest_json)(timeout)
        return parse_release(payload, current), ""
    except Exception:
        return {}, NO_NETWORK_MESSAGE


def valid_release_url(url):
    prefix = f"https://github.com/{GITHUB_REPOSITORY}/releases/tag/"
    return isinstance(url, str) and url.startswith(prefix) and len(url) > len(prefix)


def probe_release_page(url, timeout=5.0, opener=None):
    """打开浏览器前确认 GitHub 发布页可达，避免断网时假装已打开。"""
    if not valid_release_url(url):
        return False, NO_NETWORK_MESSAGE
    try:
        request = Request(
            url,
            headers={
                "Accept": "text/html",
                "User-Agent": f"BestYolo/{APP_VERSION}",
            },
        )
        with (opener or _https_opener()).open(
                request, timeout=float(timeout)) as response:
            status = int(getattr(response, "status", 200) or 200)
        if 200 <= status < 400:
            return True, ""
    except Exception:
        pass
    return False, NO_NETWORK_MESSAGE
