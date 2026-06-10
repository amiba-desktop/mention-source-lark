# amiba-mention-source-lark

An amiba backplane **mention source** that makes Feishu (Lark) resources —
documents, group chats, people — `@`-mentionable in the composer, and ships
the agent-side resolver that reads them.

It is a standalone, publicly-installable mention source (no special "preset"
status): it goes in through the same `/hermes/mention-sources` install path
any third-party source would, which is exactly what keeps the backplane's
mention-resource contract honest. It is the reference implementation for
amiba's mention-source author guide.

It is **HTTP-agnostic** — it exposes a plain `search` capability and a
manifest; the backplane's built-in mention-sources framework
(`amiba_backplane/runtime/mention_sources/`) loads those and adapts `search`
into `GET /mention-sources/lark/search` for the composer. lark itself never
imports a web framework.

## What it provides

- **`search` capability** — `async search(rtype, query, limit) -> {ok, items}`
  ([source.py](source.py)) shells out to `lark-cli` to list matching Feishu
  docs / groups / people. `rtype` ∈ `doc | chat | user`; each item is
  `{ id, title, detail, payload }`. Degrades to `{ok: True, items: []}` when
  `lark-cli` is missing/unconfigured (never raises for "no results").
- **Mention resources** — `mention-source.yaml` declares `mention_resources`
  for `lark.doc` / `lark.chat` / `lark.user`, which the backplane aggregates
  into `GET /hermes/mention-resources`. The composer turns each into a
  generic `@`-provider; on send the picked resource expands into a
  self-describing reference line (e.g. `[飞书文档] 标题 — https://…`).
- **Resolver skill** — `skills/lark-resolve.md` teaches the agent to turn
  those reference lines into content/actions via `lark-cli`. Installed into
  `skills.external_dirs` automatically by the backplane.

## Requirements

- The amiba desktop app (it spawns the backplane on `127.0.0.1:9394`).
- `lark-cli` on PATH, configured for the user's workspace.

## Install

This is an amiba **mention source**, installed via the backplane admin API (or
the desktop **Settings → Mention Sources** panel):

```bash
# editable local checkout (symlink; edits are live):
curl -XPOST 127.0.0.1:9394/hermes/mention-sources \
  -d '{"from_path":"/path/to/amiba-mention-source-lark","name":"lark"}'

# or from git (name read from mention-source.yaml):
curl -XPOST 127.0.0.1:9394/hermes/mention-sources \
  -d '{"from_git":"https://github.com/amiba-desktop/amiba-mention-source-lark"}'
```

Verify with `curl 127.0.0.1:9394/hermes/mention-sources`; the resolver skill
becomes available to the agent on the next gateway start.

## Layout

```
mention-source.yaml     # name + mention_resources + resolver_skill
__init__.py             # re-exports the `search` capability for the loader
source.py               # lark-cli subprocess wrapper + async search()
skills/lark-resolve.md  # agent-side resolver
```
