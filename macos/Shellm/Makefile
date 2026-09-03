APP      = Shellm.app
BINARY   = $(APP)/Contents/MacOS/Shellm
PLIST    = $(APP)/Contents/Info.plist
SOURCES  = main.swift

.PHONY: app clean

app: $(BINARY) $(PLIST)
	@codesign --force --sign - $(APP)

$(BINARY): $(SOURCES)
	@mkdir -p $(APP)/Contents/MacOS
	swiftc $(SOURCES) -o $(BINARY) \
		-framework Cocoa -framework SwiftUI \
		-framework UserNotifications -O

$(PLIST): Info.plist
	@mkdir -p $(APP)/Contents
	cp Info.plist $(PLIST)

clean:
	rm -rf $(APP)
