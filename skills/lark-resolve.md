---
name: lark-resolve
description: >
  Resolve Feishu (Lark) resource handles that appear in a message —
  documents, group chats, and people — into their actual content or into
  an action, using lark-cli (and the other lark-* skills). Use when a
  message contains a Feishu mention handle and you need to read it or act
  on it.
when_to_use: >
  The user's message contains a Feishu handle produced by an @-mention,
  i.e. a line like "[飞书文档] <title> — <url>", "[飞书群] <name>
  (chat_id=...)", or "[飞书联系人] <name> (chat=...)", AND the task needs
  that resource's content or an action against it (read the doc, summarize
  the group's recent messages, send to that person, etc.).
---

# Resolving Feishu mention handles

Feishu resources mentioned in a message arrive as **self-describing
reference lines**, not as inlined content. Each line tells you the resource
type and the identifier you need to act on it. Resolve them on demand —
only fetch what the task actually requires.

## Prerequisite — `lark-cli` must be installed

This skill resolves handles by shelling out to **`lark-cli`**, so that
binary must be on `PATH` and configured (authenticated) for the user's
Feishu workspace. It is the same `lark-cli` the other `lark-*` skills use;
the mention source also declares it in `mention-source.yaml`
(`requires.binaries: [lark-cli]`).

If `lark-cli` is not found (`command not found` / "not configured"), do
**not** invent the resource's contents — tell the user the handle can't be
resolved because `lark-cli` isn't installed/configured, and point them at
installing and authenticating it for their workspace.

## Handle formats

| Looks like | Type | Key identifier |
|---|---|---|
| `[飞书文档] <title> — <url>` | doc / sheet / wiki | the `<url>` |
| `[飞书群] <name> (chat_id=<id>)` | group chat | the `chat_id` |
| `[飞书联系人] <name> (chat=<p2p_chat_id>)` | person | their 1:1 `p2p_chat_id` |

## How to resolve

Shell out to `lark-cli` (it's on the user's machine and already
authenticated — the same tool the other `lark-*` skills use). Pass
`--format json` and read the result.

- **Doc** — read its content by URL:
  ```bash
  lark-cli docs +read --url "<url>" --format json
  ```
  (If you have the `lark-doc` skill loaded, prefer its richer read flow.)

- **Group chat** — read recent messages / metadata by chat_id:
  ```bash
  lark-cli im +messages --chat-id "<chat_id>" --format json
  ```
  (See the `lark-im` skill for sending, history paging, etc.)

- **Person** — their `p2p_chat_id` is the 1:1 chat; treat it as a chat
  target for reading or sending:
  ```bash
  lark-cli im +messages --chat-id "<p2p_chat_id>" --format json
  ```

## Notes

- Resolve lazily: if the task only needs the doc's title (already in the
  handle), don't fetch the body.
- Degrade gracefully: if `lark-cli` is missing or a call fails, tell the
  user the handle couldn't be resolved and what you'd need — don't invent
  contents.
- This skill is the bridge from the mention handle to action. The actual
  Feishu read/write capabilities live in `lark-cli` and the `lark-*`
  skills; lean on them rather than reimplementing.
