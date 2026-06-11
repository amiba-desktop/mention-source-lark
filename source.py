"""The mention source's ``search`` capability — wraps the ``lark-cli`` subprocess.

Self-contained: no aiohttp / web imports, no awareness of routes. The backplane's
mention-sources gateway reads :func:`search` from the in-process registry and
adapts it into ``GET /mention-sources/lark/search`` for the composer; any other
in-process consumer can call it directly too.

Why this exists
---------------
The browser extension has no Feishu auth — it can't list the user's
groups / contacts / docs to populate a mention picker. ``lark-cli`` (already
on the user's machine, used by the Hermes lark skills) can. We shell out to
it across three entity types:

  - group chats  (``lark-cli im +chat-search``)
  - people       (``lark-cli contact +search-user``)
  - docs / sheets / wiki  (``lark-cli docs +search``)

Each search returns items shaped ``{id, title, detail, payload}`` where
``payload`` carries exactly the fields the source's ``mention_resources``
declaration lists, so the composer can build the mention chip and the
``serialize`` template can interpolate them.

Failure modes degrade gracefully: lark-cli missing on PATH, workspace not
configured, or per-call timeout all surface as empty result lists plus an
optional ``error`` string. Callers should treat this as "show free-text
fallback", never as a transport failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("hermes-lark")

_LARK_CLI_TIMEOUT_S = 15


def _hermes_home() -> Path:
    """Resolve ``HERMES_HOME`` without depending on backplane internals."""
    try:
        from hermes_constants import get_hermes_home  # type: ignore

        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def _lark_env() -> Dict[str, str]:
    """Environment for the lark-cli subprocess.

    lark-cli stores its config per *workspace* (``~/.lark-cli/<ws>/``) and
    auto-detects the workspace from ``HERMES_HOME``. Without it, lark-cli
    falls back to the unconfigured default workspace and every call comes
    back "not configured" — even though the agent's own lark skills work
    fine (they run with HERMES_HOME set). So we set it explicitly here.
    """
    env = dict(os.environ)
    env.setdefault("HERMES_HOME", str(_hermes_home()))
    return env


async def _run_lark(args: List[str]) -> Dict[str, Any]:
    """Run one lark-cli command. Returns ``{ok, data}`` or ``{ok: False, error}``."""
    exe = shutil.which("lark-cli")
    if not exe:
        return {"ok": False, "error": "lark-cli not found on PATH"}
    try:
        proc = await asyncio.create_subprocess_exec(
            exe,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_lark_env(),
        )
        out, err = await asyncio.wait_for(
            proc.communicate(), timeout=_LARK_CLI_TIMEOUT_S
        )
    except asyncio.TimeoutError:
        return {"ok": False, "error": "lark-cli timed out"}
    except Exception as exc:  # pragma: no cover - subprocess edge cases
        logger.warning("lark-cli failed (%s): %s", args[:2], exc)
        return {"ok": False, "error": f"lark-cli failed: {exc}"}

    # lark-cli writes result JSON to stdout on success but to stderr for
    # config/auth errors, so we try both streams.
    data: Any = None
    for raw in (out, err):
        text = (raw or b"").decode("utf-8", "replace").strip()
        if not text:
            continue
        try:
            data = json.loads(text)
            break
        except Exception:
            continue
    if data is None:
        return {"ok": False, "error": "lark-cli returned unparseable output"}
    if isinstance(data, dict) and data.get("ok") is False:
        err_obj = data.get("error")
        if isinstance(err_obj, dict):
            msg = err_obj.get("message") or "lark-cli error"
        elif isinstance(err_obj, str):
            msg = err_obj
        else:
            msg = "lark-cli error"
        return {"ok": False, "error": msg}
    return {"ok": True, "data": data}


def _strip_highlight(text: str) -> str:
    """Drop the ``<h>...</h>`` markers lark-cli puts around matched terms."""
    return re.sub(r"</?h>", "", text or "").strip()


def _first_list(node: Any, keys: tuple) -> List[Dict[str, Any]]:
    """Find the first list under any of ``keys`` in a (possibly nested) dict."""
    if isinstance(node, dict):
        for k in keys:
            v = node.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        for v in node.values():
            found = _first_list(v, keys)
            if found:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _first_list(v, keys)
            if found:
                return found
    return []


# ---------------------------------------------------------------------------
# Per-entity searches → items shaped {id, title, detail, payload}
# ---------------------------------------------------------------------------


def _map_chats(data: Any) -> List[Dict[str, Any]]:
    """Shape a lark-cli chat payload into ``{id,title,detail,payload}`` items.

    Shared by keyword search (``im +chat-search``) and the keyword-free default
    listing (``im chats list``) — both nest their chats under ``chats``/``items``.
    """
    items: List[Dict[str, Any]] = []
    seen = set()
    for c in _first_list(data, ("chats", "items")):
        cid = c.get("chat_id") or c.get("id")
        name = c.get("name") or c.get("chat_name")
        if not isinstance(cid, str) or not isinstance(name, str) or cid in seen:
            continue
        seen.add(cid)
        detail = c.get("description") if isinstance(c.get("description"), str) else ""
        items.append(
            {
                "id": cid,
                "title": name,
                "detail": detail,
                "payload": {"chat_id": cid, "name": name},
            }
        )
    return items


async def _search_chats(query: str, limit: int) -> Dict[str, Any]:
    res = await _run_lark(
        ["im", "+chat-search", "--query", query, "--page-size", str(limit), "--format", "json"]
    )
    if not res.get("ok"):
        return {"items": [], "error": res.get("error")}
    return {"items": _map_chats(res["data"]), "error": None}


async def _list_chats(limit: int) -> Dict[str, Any]:
    """Keyword-free default: the user's joined group chats (``im chats list``).

    Chat is the one entity type with a no-query listing, so the composer can
    show a default batch the moment ``@`` opens (doc/user search demand a term).
    """
    res = await _run_lark(
        ["im", "chats", "list", "--as", "user",
         "--params", json.dumps({"page_size": limit}), "--format", "json"]
    )
    if not res.get("ok"):
        return {"items": [], "error": res.get("error")}
    return {"items": _map_chats(res["data"]), "error": None}


async def _search_users(query: str, limit: int) -> Dict[str, Any]:
    # contact +search-user caps --page-size at 30 (chat/doc allow 50).
    res = await _run_lark(
        ["contact", "+search-user", "--queries", query,
         "--page-size", str(min(limit, 30)), "--format", "json"]
    )
    if not res.get("ok"):
        return {"items": [], "error": res.get("error")}
    items: List[Dict[str, Any]] = []
    seen = set()
    for u in _first_list(res["data"], ("users", "items")):
        # Target a person via their 1:1 (p2p) chat — that's what a digest
        # "watch this person" / mention source actually reads. Skip users
        # with no p2p chat (can't be addressed as a private chat).
        p2p = u.get("p2p_chat_id")
        name = u.get("localized_name") or u.get("name")
        if not isinstance(p2p, str) or not p2p or not isinstance(name, str):
            continue
        if p2p in seen:
            continue
        seen.add(p2p)
        dept = u.get("department")
        email = u.get("email")
        detail = dept if isinstance(dept, str) and dept else (
            email if isinstance(email, str) else ""
        )
        items.append(
            {
                "id": p2p,
                "title": name,
                "detail": detail,
                "payload": {"p2p_chat_id": p2p, "name": name},
            }
        )
    return {"items": items, "error": None}


async def _search_docs(query: str, limit: int) -> Dict[str, Any]:
    res = await _run_lark(
        ["docs", "+search", "--query", query, "--page-size", str(limit), "--format", "json"]
    )
    if not res.get("ok"):
        return {"items": [], "error": res.get("error")}
    items: List[Dict[str, Any]] = []
    seen = set()
    for r in _first_list(res["data"], ("results", "items")):
        meta = r.get("result_meta") if isinstance(r.get("result_meta"), dict) else {}
        url = meta.get("url")
        title = _strip_highlight(r.get("title_highlighted") or "") or meta.get("title", "")
        if not isinstance(url, str) or not url or not title or url in seen:
            continue
        seen.add(url)
        doc_type = meta.get("doc_types") or r.get("entity_type") or ""
        items.append(
            {
                "id": url,
                "title": title,
                "detail": str(doc_type),
                "payload": {"url": url, "title": title},
            }
        )
    return {"items": items, "error": None}


# ---------------------------------------------------------------------------
# Public dispatcher — one resource type per call
# ---------------------------------------------------------------------------

_SEARCHERS = {
    "doc": _search_docs,
    "chat": _search_chats,
    "user": _search_users,
}


async def search(rtype: str, query: str, limit: int = 8) -> Dict[str, Any]:
    """Search one Feishu resource type. Returns ``{ok, items, error?}``.

    Empty query: ``chat`` lists the user's joined groups (a useful default the
    moment ``@`` opens); ``doc``/``user`` need a keyword (declared
    ``requires_query`` in the manifest) so they return empty and the composer
    shows their ``empty_hint``. Unknown / missing ``rtype`` returns empty
    (graceful — the composer just shows no candidates), never an error.
    """
    query = (query or "").strip()
    searcher = _SEARCHERS.get(rtype)
    if searcher is None:
        return {"ok": True, "items": []}
    limit = max(1, min(50, int(limit or 8)))
    if not query:
        if rtype == "chat":
            r = await _list_chats(limit)
        else:
            return {"ok": True, "items": []}
    else:
        r = await searcher(query, limit)
    payload: Dict[str, Any] = {"ok": True, "items": r["items"]}
    if not r["items"] and r.get("error"):
        payload["error"] = r["error"]
    return payload
