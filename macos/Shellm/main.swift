import Cocoa
import SwiftUI
import UserNotifications

// MARK: - 1. App Entry Point

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()

class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    var statusItem: NSStatusItem!
    var popover: NSPopover!
    let model = ChatModel()
    var settingsWindow: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let nc = UNUserNotificationCenter.current()
        nc.delegate = self
        nc.requestAuthorization(options: [.alert, .sound, .badge]) { granted, _ in
            if !granted { NSLog("Shellm: notification permission denied") }
        }
        promptAccessibilityIfNeeded()

        // Enable Edit menu (paste/copy/cut/select-all) in popover
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        let editItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        editItem.submenu = editMenu
        NSApp.mainMenu = NSMenu()
        NSApp.mainMenu?.addItem(editItem)

        // Status bar item
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "bubble.left.fill",
                                   accessibilityDescription: "Shellm")
            button.action = #selector(togglePopover)
            button.target = self
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }

        // Popover with ChatView
        popover = NSPopover()
        popover.contentSize = NSSize(width: 420, height: 520)
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(
            rootView: ChatView(model: model, openSettings: { [weak self] in self?.openSettings() })
        )

        model.statusItem = statusItem
        model.popover = popover
    }

    @objc func togglePopover() {
        guard let event = NSApp.currentEvent, let button = statusItem.button else { return }
        if event.type == .rightMouseUp {
            let menu = NSMenu()
            menu.addItem(NSMenuItem(title: "Quit Shellm", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
            statusItem.menu = menu
            button.performClick(nil)
            // Clear menu so left-click goes back to popover
            DispatchQueue.main.async { self.statusItem.menu = nil }
            return
        }
        if popover.isShown {
            popover.performClose(nil)
        } else {
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    func openSettings() {
        popover.performClose(nil)
        if let w = settingsWindow, w.isVisible {
            w.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let settingsView = SettingsView(model: model)
        let controller = NSHostingController(rootView: settingsView)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 380),
                              styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.isReleasedWhenClosed = false
        window.contentViewController = controller
        window.title = "Shellm Settings"
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        settingsWindow = window
    }

    // Show notifications even when app is in foreground
    func userNotificationCenter(_ center: UNUserNotificationCenter,
                                willPresent notification: UNNotification,
                                withCompletionHandler handler: @escaping (UNNotificationPresentationOptions) -> Void) {
        handler([.banner, .sound])
    }

    func promptAccessibilityIfNeeded() {
        // Check without prompting first
        let trusted = AXIsProcessTrusted()
        if !trusted {
            // Only prompt if not already trusted
            AXIsProcessTrustedWithOptions(
                [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary)
        }
    }
}

// MARK: - 2. Codable API Structs

struct ChatMessage: Codable, Identifiable, Equatable {
    var id: String { "\(step_id)-\(ts)" }
    let ts: String
    let step_id: String
    let from: String
    let to: String
    let content: String
    let reply_to: String?
    let filename: String?
}

struct IdentityRef: Codable {
    let id: String
    let name: String
}

struct ChatResponse: Codable {
    let identity: IdentityRef
    let live: Bool
    let messages: [ChatMessage]
    let outcomes: [String: String]
}

struct SendResponse: Codable {
    let ok: Bool
    let from: String
    let to: String
}

struct IdentityListItem: Codable, Identifiable {
    let id: String
    let name: String
    let live: Bool
}

// MARK: - 3. Secret File Storage

private let secretPath: String = {
    let dir = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".config/shellm")
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    // Owner-only permissions
    try? FileManager.default.setAttributes(
        [.posixPermissions: 0o700], ofItemAtPath: dir.path)
    return dir.appendingPathComponent("cf-secret").path
}()

func saveSecret(_ value: String) {
    FileManager.default.createFile(atPath: secretPath,
        contents: Data(value.utf8), attributes: [.posixPermissions: 0o600])
}

func loadSecret() -> String {
    guard let data = FileManager.default.contents(atPath: secretPath) else { return "" }
    return String(data: data, encoding: .utf8) ?? ""
}

// MARK: - 4. API Functions

func buildRequest(url: URL, cfClientId: String, cfSecret: String) -> URLRequest {
    var req = URLRequest(url: url)
    if !cfClientId.isEmpty && !cfSecret.isEmpty {
        req.setValue(cfClientId, forHTTPHeaderField: "CF-Access-Client-Id")
        req.setValue(cfSecret, forHTTPHeaderField: "CF-Access-Client-Secret")
    }
    return req
}

func fetchChat(server: String, identityId: String, fromName: String,
               cfClientId: String, cfSecret: String) async throws -> ChatResponse {
    let encoded = identityId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? identityId
    let withParam = fromName.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? fromName
    guard let url = URL(string: "\(server)/api/identities/\(encoded)/chat?tail=200&with=\(withParam)") else {
        throw URLError(.badURL)
    }
    let req = buildRequest(url: url, cfClientId: cfClientId, cfSecret: cfSecret)
    let (data, _) = try await URLSession.shared.data(for: req)
    return try JSONDecoder().decode(ChatResponse.self, from: data)
}

func sendChat(server: String, identityId: String, content: String, fromName: String,
              cfClientId: String, cfSecret: String) async throws -> SendResponse {
    let encoded = identityId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? identityId
    guard let url = URL(string: "\(server)/api/identities/\(encoded)/chat") else {
        throw URLError(.badURL)
    }
    var req = buildRequest(url: url, cfClientId: cfClientId, cfSecret: cfSecret)
    req.httpMethod = "POST"
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.httpBody = try JSONEncoder().encode(["content": content, "from_name": fromName])
    let (data, _) = try await URLSession.shared.data(for: req)
    return try JSONDecoder().decode(SendResponse.self, from: data)
}

func fetchIdentities(server: String, cfClientId: String, cfSecret: String) async throws -> [IdentityListItem] {
    guard let url = URL(string: "\(server)/api/identities") else {
        throw URLError(.badURL)
    }
    let req = buildRequest(url: url, cfClientId: cfClientId, cfSecret: cfSecret)
    let (data, _) = try await URLSession.shared.data(for: req)
    return try JSONDecoder().decode([IdentityListItem].self, from: data)
}

// MARK: - 5. ChatModel

class ChatModel: ObservableObject {
    @AppStorage("serverURL") var serverURL = "http://localhost:8080"
    @AppStorage("fromName") var fromName = ""
    @AppStorage("identityId") var identityId = ""
    @AppStorage("cfClientId") var cfClientId = ""
    @AppStorage("hotkeyCode") var hotkeyCode: Int = 49    // Space
    @AppStorage("hotkeyMods") var hotkeyMods: Int = 524288 // Option

    @Published var messages: [ChatMessage] = []
    @Published var outcomes: [String: String] = [:]
    @Published var identityName = ""
    @Published var live = false
    @Published var identities: [IdentityListItem] = []
    @Published var error: String?

    weak var statusItem: NSStatusItem?
    weak var popover: NSPopover?

    var cfSecret: String {
        get { loadSecret() }
        set { saveSecret(newValue) }
    }

    var agentThinking: Bool {
        guard !messages.isEmpty else { return false }
        for msg in messages.reversed() {
            if msg.from == fromName && msg.to == identityName {
                return outcomes[msg.step_id] == nil
            }
            if msg.from == identityName { return false }
        }
        return false
    }

    private var pollTask: Task<Void, Never>?
    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?

    init() {
        startPolling()
        registerHotkey()
    }

    func startPolling() {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.poll()
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }

    @MainActor
    private func poll() async {
        guard !fromName.isEmpty else { return }

        if identityId.isEmpty {
            do {
                let list = try await fetchIdentities(server: serverURL,
                    cfClientId: cfClientId, cfSecret: cfSecret)
                identities = list
                if let first = list.first {
                    identityId = first.id
                }
            } catch {
                self.error = error.localizedDescription
            }
            guard !identityId.isEmpty else { return }
        }

        do {
            let resp = try await fetchChat(server: serverURL, identityId: identityId,
                fromName: fromName, cfClientId: cfClientId, cfSecret: cfSecret)
            let oldCount = messages.count
            if resp.messages != messages {
                messages = resp.messages
                outcomes = resp.outcomes
            }
            identityName = resp.identity.name
            live = resp.live
            self.error = nil

            // Notify on all new agent messages
            if messages.count > oldCount {
                for msg in messages.suffix(messages.count - oldCount) {
                    if msg.from == identityName {
                        notifyNewMessage(msg)
                    }
                }
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    func send(_ text: String) {
        guard !text.isEmpty, !fromName.isEmpty, !identityId.isEmpty else { return }
        Task {
            do {
                _ = try await sendChat(server: serverURL, identityId: identityId,
                    content: text, fromName: fromName,
                    cfClientId: cfClientId, cfSecret: cfSecret)
                await poll()
            } catch {
                await MainActor.run { self.error = error.localizedDescription }
            }
        }
    }

    @MainActor
    func refreshIdentities() {
        Task { @MainActor in
            do {
                let list = try await fetchIdentities(server: serverURL,
                    cfClientId: cfClientId, cfSecret: cfSecret)
                identities = list
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    // MARK: Global Hotkey (CGEvent tap — works in terminals and all apps)

    func registerHotkey() {
        // Tear down previous tap
        if let source = runLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes)
            runLoopSource = nil
        }
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
            eventTap = nil
        }

        // Store self pointer for the C callback
        let selfPtr = Unmanaged.passUnretained(self).toOpaque()

        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: CGEventMask(1 << CGEventType.keyDown.rawValue)
                | CGEventMask(1 << CGEventType.tapDisabledByTimeout.rawValue)
                | CGEventMask(1 << CGEventType.tapDisabledByUserInput.rawValue),
            callback: { (proxy, type, event, refcon) -> Unmanaged<CGEvent>? in
                guard let refcon = refcon else { return Unmanaged.passUnretained(event) }
                let model = Unmanaged<ChatModel>.fromOpaque(refcon).takeUnretainedValue()

                // macOS disables taps that take too long — re-enable
                if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
                    if let tap = model.eventTap {
                        CGEvent.tapEnable(tap: tap, enable: true)
                    }
                    return Unmanaged.passUnretained(event)
                }

                let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
                let flags = event.flags.intersection([.maskAlternate, .maskCommand, .maskShift, .maskControl])
                let wantedFlags = CGEventFlags(rawValue: UInt64(model.hotkeyMods))
                    .intersection([.maskAlternate, .maskCommand, .maskShift, .maskControl])
                if keyCode == Int64(model.hotkeyCode) && flags == wantedFlags {
                    DispatchQueue.main.async { model.togglePanel() }
                    return nil  // swallow the event
                }
                return Unmanaged.passUnretained(event)
            },
            userInfo: selfPtr
        ) else {
            NSLog("Shellm: CGEvent tap failed — Accessibility permission not granted")
            return
        }

        eventTap = tap
        runLoopSource = CFMachPortCreateRunLoopSource(nil, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), runLoopSource, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
    }

    func togglePanel() {
        guard let statusItem = statusItem, let button = statusItem.button else { return }
        guard let popover = popover else { return }
        if popover.isShown {
            popover.performClose(nil)
        } else {
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            popover.contentViewController?.view.window?.makeKey()
        }
    }

    // MARK: Notifications

    private func notifyNewMessage(_ msg: ChatMessage) {
        let content = UNMutableNotificationContent()
        content.title = msg.from
        content.body = String(msg.content.prefix(200))
        content.sound = .default
        let req = UNNotificationRequest(identifier: msg.id,
            content: content, trigger: nil)
        UNUserNotificationCenter.current().add(req)
    }
}

// MARK: - 6. ChatView + MessageRow

struct ChatView: View {
    @ObservedObject var model: ChatModel
    var openSettings: () -> Void
    @State private var draft = ""
    @FocusState private var inputFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text(model.identityName.isEmpty ? "Shellm" : model.identityName)
                    .font(.headline)
                Circle()
                    .fill(model.live ? Color.green : Color.red)
                    .frame(width: 8, height: 8)
                    .help(model.live ? "Agent is live" : "Agent is offline")
                if model.agentThinking {
                    ProgressView()
                        .scaleEffect(0.5)
                        .frame(width: 16, height: 16)
                    Text("thinking...")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Spacer()
                if let err = model.error {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.orange)
                        .help(err)
                }
                Button(action: openSettings) {
                    Image(systemName: "gear")
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color(nsColor: .windowBackgroundColor))

            Divider()

            // Messages
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 4) {
                        ForEach(model.messages) { msg in
                            MessageRow(msg: msg, identityName: model.identityName)
                                .id(msg.id)
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                }
                .onChange(of: model.messages.count) {
                    if let last = model.messages.last {
                        withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
            }

            Divider()

            // Input bar
            HStack(spacing: 8) {
                TextField("Message...", text: $draft)
                    .textFieldStyle(.plain)
                    .focused($inputFocused)
                    .onSubmit { sendDraft() }
                Button(action: sendDraft) {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.title2)
                }
                .buttonStyle(.plain)
                .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
        .onAppear { inputFocused = true }
    }

    private func sendDraft() {
        let text = draft.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        model.send(text)
        draft = ""
    }
}

struct MessageRow: View {
    let msg: ChatMessage
    let identityName: String

    private var isAgent: Bool { msg.from == identityName }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                Text(msg.from)
                    .font(.caption.bold())
                    .foregroundColor(isAgent ? .green : .blue)
                Text(formatTime(msg.ts))
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
            Text(msg.content)
                .font(.body)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 2)
    }

    private func formatTime(_ ts: String) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = formatter.date(from: ts) else {
            formatter.formatOptions = [.withInternetDateTime]
            guard let date = formatter.date(from: ts) else { return ts }
            return timeString(date)
        }
        return timeString(date)
    }

    private func timeString(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f.string(from: date)
    }
}

// MARK: - 7. SettingsView

struct SettingsView: View {
    @ObservedObject var model: ChatModel
    @State private var cfSecretField = ""
    @State private var recordingHotkey = false
    @State private var connStatus: String?
    @State private var connOk = false
    @State private var testing = false

    var body: some View {
        Form {
            Section("Server") {
                TextField("URL", text: $model.serverURL)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { testConnection() }
                HStack(spacing: 8) {
                    Button("localhost:8080") { model.serverURL = "http://localhost:8080"; testConnection() }
                    Spacer()
                    if testing {
                        ProgressView().scaleEffect(0.5).frame(width: 16, height: 16)
                    } else if let status = connStatus {
                        Image(systemName: connOk ? "checkmark.circle.fill" : "xmark.circle.fill")
                            .foregroundColor(connOk ? .green : .red)
                        Text(status).font(.caption).foregroundColor(.secondary)
                    }
                }
                .buttonStyle(.link)
            }

            Section("Identity") {
                TextField("Your name (from_name)", text: $model.fromName)
                Picker("Identity", selection: $model.identityId) {
                    Text("Auto (first available)").tag("")
                    ForEach(model.identities) { ident in
                        HStack {
                            Text(ident.name)
                            Circle()
                                .fill(ident.live ? Color.green : Color.red)
                                .frame(width: 6, height: 6)
                        }
                        .tag(ident.id)
                    }
                }
                Button("Refresh Identities") { model.refreshIdentities() }
            }

            Section("Cloudflare Access (optional)") {
                TextField("CF-Access-Client-Id", text: $model.cfClientId)
                SecureField("CF-Access-Client-Secret", text: $cfSecretField)
                    .onAppear { cfSecretField = model.cfSecret }
                    .onChange(of: cfSecretField) {
                        model.cfSecret = cfSecretField
                    }
            }

            Section("Global Shortcut") {
                HStack {
                    Text("Hotkey:")
                    if recordingHotkey {
                        Text("Press keys...")
                            .foregroundColor(.secondary)
                            .italic()
                    } else {
                        Text(hotkeyLabel())
                            .font(.system(.body, design: .monospaced))
                    }
                    Spacer()
                    Button(recordingHotkey ? "Cancel" : "Record") {
                        if recordingHotkey {
                            recordingHotkey = false
                        } else {
                            recordingHotkey = true
                            NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
                                guard self.recordingHotkey else { return event }
                                self.model.hotkeyCode = Int(event.keyCode)
                                self.model.hotkeyMods = Int(event.modifierFlags.intersection(.deviceIndependentFlagsMask).rawValue)
                                self.model.registerHotkey()
                                self.recordingHotkey = false
                                return nil
                            }
                        }
                    }
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 400, height: 380)
        .onAppear { model.refreshIdentities(); testConnection() }
    }

    private func testConnection() {
        testing = true
        connStatus = nil
        Task {
            do {
                let list = try await fetchIdentities(server: model.serverURL,
                    cfClientId: model.cfClientId, cfSecret: model.cfSecret)
                await MainActor.run {
                    testing = false
                    connOk = true
                    connStatus = "\(list.count) identit\(list.count == 1 ? "y" : "ies")"
                    model.identities = list
                }
            } catch {
                await MainActor.run {
                    testing = false
                    connOk = false
                    let msg = error.localizedDescription
                    if msg.contains("refused") { connStatus = "refused" }
                    else if msg.contains("timed out") { connStatus = "timeout" }
                    else { connStatus = "error" }
                }
            }
        }
    }

    private func hotkeyLabel() -> String {
        var parts: [String] = []
        let mods = NSEvent.ModifierFlags(rawValue: UInt(model.hotkeyMods))
        if mods.contains(.control) { parts.append("\u{2303}") }
        if mods.contains(.option)  { parts.append("\u{2325}") }
        if mods.contains(.shift)   { parts.append("\u{21E7}") }
        if mods.contains(.command) { parts.append("\u{2318}") }

        let keyNames: [Int: String] = [
            49: "Space", 36: "Return", 48: "Tab", 51: "Delete", 53: "Esc",
            0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X",
            8: "C", 9: "V", 11: "B", 12: "Q", 13: "W", 14: "E", 15: "R",
            16: "Y", 17: "T", 31: "O", 32: "U", 34: "I", 35: "P", 37: "L",
            38: "J", 40: "K", 45: "N", 46: "M",
        ]
        parts.append(keyNames[model.hotkeyCode] ?? "Key\(model.hotkeyCode)")
        return parts.joined()
    }
}
