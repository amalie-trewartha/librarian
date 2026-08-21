# Shellm.app — minimal native macOS chat client

**Status: implemented** — `macos/Shellm/` (main.swift, Info.plist, Makefile).
`make app` builds a working `.app` bundle with `swiftc`, no Xcode needed.

A menu-bar chat client for talking to a shellm agent, whether the identity
runs locally or on a remote box (e.g. the EC2 instance behind
chat.shellm.net). Design goal: the most minimal possible native client —
one Swift file, zero dependencies, no new server work.

## What it talks to

The existing `headlong-web` HTTP API (`web/src/headlong_web/server.py`) — the
same API the phone PWA uses. It is identical for local
(`http://localhost:8080`) and remote (`https://chat.shellm.net`):

| Call | Purpose |
|---|---|
| `GET /api/identities` | list identities → auto-pick or let user choose |
| `GET /api/identities/{id}/chat?tail=200&with=<you>` | returns `{live, messages[], outcomes{}}` |
| `POST /api/identities/{id}/chat` body `{content, from_name}` | send a message |

Messages arrive by **polling** (2s interval) — the PWA's model too; the
server has no chat SSE/websocket and `chat_view` is cheap.

`outcomes` maps each sent message's step_id to `replied` / `no-reply` /
`failed`. A sent message with *no* outcome yet is exactly what the server
docstring calls "a truthful typing indicator" — the client gets a real
"thinking…" state for free.

## The one real design problem: Cloudflare Access

chat.shellm.net is not just an open port. Per `deploy/DEPLOY.md`, the app
is auth-free on `127.0.0.1:8080` behind a Cloudflare Tunnel, and **all
auth lives in Cloudflare Access** (SSO / email OTP). A URLSession client
can't do that browser login dance. The minimal, standard fix is a
Cloudflare **service token**:

1. Zero Trust dashboard → create a service token (yields a Client ID +
   Secret pair).
2. Add a "Service Auth" policy on the chat.shellm.net Access application
   allowing that token.
3. The app sends two static headers on every request:
   `CF-Access-Client-Id` and `CF-Access-Client-Secret`.

That's two optional text fields in the app's settings, left empty when
pointing at localhost. No OAuth flows. The secret is stored in
`~/.config/shellm/cf-secret` (mode 0600) — Keychain's
`SecItemCopyMatching` crashes on unsigned app bundles built with `swiftc`.

## App shape

**`NSStatusBar` + `NSPopover`** — a chat panel that drops down from the
menu bar. `MenuBarExtra` was tried first but doesn't render reliably when
built outside Xcode; the classic `NSStatusItem`/`NSPopover` pair works
everywhere. Minimal form factor for "talk to my agent": always reachable,
no dock presence, no window management. Zero third-party dependencies.

One Swift file, ~350 lines, five pieces:

1. **`Config`** — `@AppStorage`-backed: server URL, your name
   (`from_name`, the `.chatrc default_send_from` analog), identity id
   (blank = first from `/api/identities`), CF token pair. A picker for
   the known servers (`http://localhost:8080`, `https://chat.shellm.net`).
2. **`API`** (~60 lines) — two `Codable` structs mirroring the JSON
   above, `fetchChat()` and `send()` with async/await, CF headers
   injected when configured.
3. **`ChatModel: ObservableObject`** (~80 lines) — a poll `Task` loop;
   re-publish only when the message list actually changed; derives
   `agentThinking` from unanswered outcomes; sets the live dot from the
   response's `live` field.
4. **`ChatView`** (~120 lines) — scrollback of sender-colored lines
   (agent green, you blue, mirroring the TUI), auto-scroll to bottom,
   `TextField.onSubmit` to send, red/green live dot in the header.
5. **Notifications** (~25 lines, the only "feature") —
   `UNUserNotificationCenter` local notification when a new agent→you
   message lands while the panel is closed. Replaces the PWA's web-push
   without touching the server's push endpoints.

## Build without Xcode

A `Makefile` + `Info.plist` producing `Shellm.app` via `swiftc` — no
`.xcodeproj`, keeping it genuinely minimal and matching the repo's style
(`tui/` gets a native sibling: `macos/`).

Layout:

```
macos/Shellm/
  main.swift      # the whole app
  Info.plist
  Makefile        # `make app` → Shellm.app
```

ATS note: `NSAllowsArbitraryLoads` is enabled in Info.plist because
Tailscale IPs (100.x.x.x) are not considered "local networking" by
Apple's `NSAllowsLocalNetworking`, and shellm commonly runs on LAN/VPN
hosts over plain HTTP.

## Global keyboard shortcut

A system-wide hotkey (e.g. `⌥Space` or user-configurable) toggles the
chat panel open/closed — the primary way to summon the agent. This is
the menu-bar form factor's killer feature: the agent is always one
keystroke away regardless of which app has focus.

Implementation: `CGEvent.tapCreate` at the session level — this
intercepts keystrokes before any app (including terminals) sees them,
unlike `NSEvent.addGlobalMonitorForEvents` which is observe-only and
unreliable. Requires Accessibility permission (the app prompts on first
launch via `AXIsProcessTrustedWithOptions`). Store the binding in
`@AppStorage` with a settings UI to remap it (a simple "press keys"
recorder via `NSEvent.keyCode` + modifier flags).

The shortcut should also focus the text input field so the user can
immediately start typing — open panel and begin chatting in a single
keystroke.

## Deliberately left out

Sub-trajectory browsing, mindlog, thinker controls, message pagination,
multiple simultaneous conversations — all exist in the API but the PWA
already covers them. This client is send + read + notify.

The zero-code baseline it competes with: Safari's File → Add to Dock on
chat.shellm.net gives a dock-icon web app with working push. The native
client's actual wins are localhost support, service-token auth (no cookie
expiry re-logins), and the menu-bar form factor.
