#!/bin/bash
# Smoke test for the planned "toolkit app" launcher mechanics on macOS (Tahoe / macOS 26).
#
# What it proves, end to end, WITHOUT any code signing or Apple Developer account:
#   1. A .app generated LOCALLY (osacompile + custom icon + ad-hoc codesign) double-clicks
#      cleanly from Finder — no Gatekeeper prompt, no "damaged" dialog — because locally
#      created files never carry the com.apple.quarantine attribute.
#   2. The applet can detach a long-running local server and quit; the server keeps running.
#   3. The server survives laptop sleep/wake (heartbeat log proves it resumed).
#   4. A localhost HTTP server + browser-open works from that detached context with no
#      Local Network or firewall prompt (loopback is exempt).
#   5. What TCC does when the detached server touches ~/Documents (informative either way).
#
# Run on the Mac, in Terminal:
#   bash mac_launcher_smoke_test.sh            # build everything, then double-click the app
#   bash mac_launcher_smoke_test.sh check1     # ~1 min after double-clicking
#   bash mac_launcher_smoke_test.sh check2     # after closing the lid >=2 min and reopening
#   bash mac_launcher_smoke_test.sh cleanup    # remove everything this test created
#
# Paste the full output of each phase back into the Claude session.
set -u

TEST_DIR="$HOME/toolkit-smoke-test"          # directly under $HOME on purpose: not TCC-protected
APP_DIR="$HOME/Applications"
APP="$APP_DIR/ToolkitSmokeTest.app"
PORT=8765

pass() { echo "PASS  $1"; }
fail() { echo "FAIL  $1"; FAILED=1; }
info() { echo "INFO  $1"; }

# ---------------------------------------------------------------- phase: setup (default)
setup() {
    if [ "$(uname)" != "Darwin" ]; then
        echo "This test must run on the Mac, not on Linux." >&2
        exit 1
    fi
    echo "=== SMOKE TEST SETUP ==="
    info "macOS $(sw_vers -productVersion) ($(sw_vers -buildVersion)), $(uname -m)"
    info "Command Line Tools: $(xcode-select -p 2>/dev/null || echo 'NOT INSTALLED')"

    # a re-run must not leave an old server heartbeating into a deleted directory
    for pidfile in "$TEST_DIR/http.pid" "$TEST_DIR/server.pid"; do
        [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null
    done
    rm -rf "$TEST_DIR" "$APP"
    mkdir -p "$TEST_DIR/www" "$APP_DIR"

    # -- the stand-in for the future `toolkit app` server -------------------------------
    cat > "$TEST_DIR/www/index.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>Toolkit smoke test</title>
<body style="font-family:-apple-system,sans-serif;margin:4rem auto;max-width:30rem">
<h1>It works.</h1><p>This page is served by the detached local server that the
double-clicked app started. The browser was opened by that server, not by you.</p></body>
HTML

    cat > "$TEST_DIR/server.sh" <<SERVER
#!/bin/bash
# Stand-in for the future NiceGUI server: heartbeat + a real localhost HTTP server.
DIR="$TEST_DIR"
if [ -f "\$DIR/server.pid" ] && kill -0 "\$(cat "\$DIR/server.pid")" 2>/dev/null; then
    echo "\$(date '+%H:%M:%S') second launch refused: server already running" >> "\$DIR/server.log"
    exit 0
fi
echo \$\$ > "\$DIR/server.pid"
echo "\$(date '+%H:%M:%S') server started, pid \$\$, PATH=\$PATH" >> "\$DIR/server.log"

if xcode-select -p >/dev/null 2>&1; then
    /usr/bin/python3 -m http.server $PORT --bind 127.0.0.1 --directory "\$DIR/www" \\
        >> "\$DIR/http.log" 2>&1 &
    echo \$! > "\$DIR/http.pid"
    # wait for the port instead of racing python's cold start
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        /usr/bin/curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/" && break
        sleep 1
    done
    /usr/bin/open "http://127.0.0.1:$PORT/"
else
    echo "no CLT; skipping http server" >> "\$DIR/server.log"
fi

n=0
while :; do
    echo "\$(date +%s) \$(date '+%H:%M:%S')" >> "\$DIR/heartbeat.log"
    n=\$((n+1))
    # ~30s in (applet long gone): does TCC prompt, silently deny, or allow?
    # Backgrounded: a pending TCC consent dialog must never stall the heartbeat.
    if [ "\$n" -eq 6 ]; then
        ( ls "\$HOME/Documents" > "\$DIR/docs_probe.log" 2>&1 \\
            && echo "(listing succeeded)" >> "\$DIR/docs_probe.log" ) &
    fi
    sleep 5
done
SERVER
    chmod +x "$TEST_DIR/server.sh"

    # -- the launcher applet, exactly as the real design would generate it --------------
    # Absolute paths throughout: Finder-launched apps (and `do shell script`) get the bare
    # launchd PATH, never the shell's.
    cat > "$TEST_DIR/launcher.applescript" <<APPLESCRIPT
on run
	try
		do shell script "echo \"applet ran \$(date '+%H:%M:%S') PATH=\$PATH\" >> '$TEST_DIR/applet.log'"
		do shell script "/bin/bash '$TEST_DIR/server.sh' > '$TEST_DIR/server_stdout.log' 2>&1 &"
	on error errMsg number errNum
		display alert "Smoke test launcher failed" message errMsg & " (" & errNum & ")"
	end try
end run
APPLESCRIPT

    if ! osacompile -o "$APP" "$TEST_DIR/launcher.applescript"; then
        echo "osacompile failed — stopping." >&2
        exit 1
    fi
    pass "osacompile built $APP"

    # -- identity: unique bundle id + the name TCC prompts would display ----------------
    /usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier org.incite.toolkit-smoke-test' \
        "$APP/Contents/Info.plist" 2>/dev/null \
        || /usr/libexec/PlistBuddy -c 'Add :CFBundleIdentifier string org.incite.toolkit-smoke-test' \
            "$APP/Contents/Info.plist"
    /usr/libexec/PlistBuddy -c 'Set :CFBundleName "Toolkit Smoke Test"' \
        "$APP/Contents/Info.plist" 2>/dev/null \
        || /usr/libexec/PlistBuddy -c 'Add :CFBundleName string "Toolkit Smoke Test"' \
            "$APP/Contents/Info.plist"

    # -- custom icon: tiny embedded PNG -> iconset -> applet.icns ------------------------
    cat > "$TEST_DIR/icon_base.b64" <<'PNG'
iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAZUlEQVR42u3QQREAAAQAMAE1kFoi
cjh7rMAiq+ezECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBAgAABAgQIECBA
gAABAgQIECBAgAABAgQIECBAgAABAu5bB1xySlttfigAAAAASUVORK5CYII=
PNG
    # macOS base64 flag drift: newer accepts -d, older only -D
    base64 -d < "$TEST_DIR/icon_base.b64" > "$TEST_DIR/icon_base.png" 2>/dev/null \
        || base64 -D < "$TEST_DIR/icon_base.b64" > "$TEST_DIR/icon_base.png"
    ICONSET="$TEST_DIR/icon.iconset"
    mkdir -p "$ICONSET"
    ICON_OK=1
    for size in 16 32 128 256 512; do
        sips -z "$size" "$size" "$TEST_DIR/icon_base.png" \
            --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1 || ICON_OK=0
        sips -z "$((size * 2))" "$((size * 2))" "$TEST_DIR/icon_base.png" \
            --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null 2>&1 || ICON_OK=0
    done
    if [ "$ICON_OK" -eq 1 ] && iconutil -c icns -o "$TEST_DIR/applet.icns" "$ICONSET" 2>&1; then
        cp "$TEST_DIR/applet.icns" "$APP/Contents/Resources/applet.icns"
        # Assets.car would override the .icns on newer macOS
        rm -f "$APP/Contents/Resources/Assets.car"
        touch "$APP"
        pass "custom icon file installed (Finder may still show a generic icon — harmless)"
    else
        info "icon generation failed — continuing with the default applet icon (non-blocking)"
    fi

    # -- ad-hoc re-sign after all modifications ------------------------------------------
    # Fatal on failure: Apple Silicon refuses to launch a bundle whose Info.plist was
    # modified after signing, so double-clicking would show a misleading "damaged" dialog
    # and contaminate the very observation this test exists to collect.
    if codesign --force -s - "$APP" 2>&1; then
        pass "ad-hoc codesign"
    else
        fail "codesign failed"
        echo "STOP — do NOT double-click the app; it cannot launch without a valid" >&2
        echo "ad-hoc signature. Paste this output back instead." >&2
        exit 1
    fi

    # -- prove there is nothing for Gatekeeper to object to ------------------------------
    if xattr -p com.apple.quarantine "$APP" >/dev/null 2>&1; then
        fail "app unexpectedly HAS a quarantine attribute"
    else
        pass "no quarantine attribute on the app (Gatekeeper should never fire)"
    fi
    info "signature: $(codesign -dv "$APP" 2>&1 | grep -E '^(Signature|TeamIdentifier)' | tr '\n' ' ')"

    open -R "$APP"
    if xcode-select -p >/dev/null 2>&1; then
        EXPECT='quits, and a browser tab opens saying "It works." (If the tab shows a
   connection error instead, reload it once and note that it did.)'
    else
        EXPECT='and quits. NOTE: this Mac has no Command Line Tools, so NO browser tab
   will open — this run only tests applet launch, heartbeat and sleep survival.'
    fi
    cat <<EOF

=== NOW DO THIS ===
1. A Finder window just opened showing ToolkitSmokeTest.app. Its icon may be a
   blue square or the generic script icon — either is fine; note which you see.
2. DOUBLE-CLICK it — this is the whole point of the test.
   WATCH FOR: any dialog at all. Expected: NONE — the app bounces in the Dock
   for a second, $EXPECT
3. ~30 seconds in, a permission dialog about Documents MAY appear. If it does:
   note the exact app name it shows, answer it, and only then continue.
4. About a minute after the double-click, run:  bash $0 check1
EOF
}

# ---------------------------------------------------------------- phase: check1
check1() {
    echo "=== CHECK 1 (after double-click) ==="
    FAILED=0

    if [ -f "$TEST_DIR/applet.log" ]; then
        pass "applet ran: $(tail -1 "$TEST_DIR/applet.log")"
    else
        fail "applet.log missing — the app never ran its script (did a dialog block it?)"
    fi

    if [ -f "$TEST_DIR/server.pid" ] && kill -0 "$(cat "$TEST_DIR/server.pid")" 2>/dev/null; then
        pass "detached server is running (pid $(cat "$TEST_DIR/server.pid")) after the applet quit"
    else
        fail "server is not running"
    fi

    if [ -f "$TEST_DIR/heartbeat.log" ]; then
        last=$(tail -1 "$TEST_DIR/heartbeat.log" | cut -d' ' -f1)
        age=$(( $(date +%s) - last ))
        n=$(wc -l < "$TEST_DIR/heartbeat.log" | tr -d ' ')
        if [ "$age" -le 10 ]; then
            pass "heartbeat is live ($n beats, last ${age}s ago)"
        else
            fail "heartbeat stale: last beat ${age}s ago"
        fi
    else
        fail "no heartbeat.log"
    fi

    if curl -s --max-time 3 "http://127.0.0.1:$PORT/" | grep -q "It works"; then
        pass "localhost HTTP server responds"
    else
        info "http server not responding (only a FAIL if CLT is installed — see server.log)"
    fi

    if [ -s "$TEST_DIR/docs_probe.log" ]; then
        info "~/Documents probe result (first lines):"
        sed 's/^/      /' "$TEST_DIR/docs_probe.log" | head -5
    elif [ -f "$TEST_DIR/docs_probe.log" ]; then
        info "~/Documents probe started but has no result yet — is a permission dialog still waiting on screen?"
    else
        info "~/Documents probe hasn't run yet (fires ~30s after server start)"
    fi
    [ -f "$TEST_DIR/server.log" ] && info "server.log: $(tr '\n' ';' < "$TEST_DIR/server.log")"

    cat <<EOF

=== ANSWER THESE (paste back with the output above) ===
A. When you double-clicked: did ANY dialog appear? (Gatekeeper warning, "damaged",
   permission prompt, anything). Expected: none.
B. Did a browser tab open by itself with "It works."?
C. Did a permission dialog about Documents appear? If yes, what app name did it show?
D. What icon did the app have in Finder — blue square or generic?

=== NEXT ===
1. Optional but useful: double-click the app a SECOND time. Expected: nothing new
   happens (no second browser tab) — the server refuses a second launch.
2. Close the lid for AT LEAST 2 minutes (on battery, not plugged into a display).
3. Reopen, wait ~20 seconds, then run:  bash $0 check2
EOF
    return "${FAILED:-0}"
}

# ---------------------------------------------------------------- phase: check2
check2() {
    echo "=== CHECK 2 (after sleep/wake) ==="
    FAILED=0

    if [ -f "$TEST_DIR/server.pid" ] && kill -0 "$(cat "$TEST_DIR/server.pid")" 2>/dev/null; then
        pass "server still running after sleep/wake"
    else
        fail "server died across sleep/wake"
    fi

    if [ -f "$TEST_DIR/heartbeat.log" ]; then
        last=$(tail -1 "$TEST_DIR/heartbeat.log" | cut -d' ' -f1)
        age=$(( $(date +%s) - last ))
        if [ "$age" -le 15 ]; then
            pass "heartbeat resumed after wake (last beat ${age}s ago)"
        else
            fail "heartbeat did not resume: last beat ${age}s ago"
        fi
        info "largest gap between beats (your sleep shows here as one big gap — that is fine):"
        awk 'NR>1 { gap=$1-prev; if (gap>max) { max=gap; at=$2 } } { prev=$1 }
             END { printf "      %ds, ending at %s\n", max, at }' "$TEST_DIR/heartbeat.log"
    else
        fail "no heartbeat.log"
    fi

    if curl -s --max-time 3 "http://127.0.0.1:$PORT/" | grep -q "It works"; then
        pass "localhost HTTP server still responds after wake"
    else
        info "http server not responding after wake"
    fi

    if [ -f "$TEST_DIR/docs_probe.log" ]; then
        info "~/Documents probe result:"
        sed 's/^/      /' "$TEST_DIR/docs_probe.log" | head -5
    fi
    [ -f "$TEST_DIR/server.log" ] && info "server.log: $(tr '\n' ';' < "$TEST_DIR/server.log")"

    cat <<EOF

=== DONE ===
Paste this output back, plus your answers to A-D from check1 if you haven't yet, and:
E. If you double-clicked the app a second time: did anything happen (second browser
   tab, dialog, anything)? Expected: nothing.
Then:  bash $0 cleanup
EOF
    return "${FAILED:-0}"
}

# ---------------------------------------------------------------- phase: cleanup
cleanup() {
    echo "=== CLEANUP ==="
    for pidfile in "$TEST_DIR/http.pid" "$TEST_DIR/server.pid"; do
        if [ -f "$pidfile" ]; then
            kill "$(cat "$pidfile")" 2>/dev/null && info "killed pid $(cat "$pidfile")"
        fi
    done
    rm -rf "$TEST_DIR" "$APP"
    info "removed $TEST_DIR and $APP"
}

case "${1:-setup}" in
    setup)   setup ;;
    check1)  check1 ;;
    check2)  check2 ;;
    cleanup) cleanup ;;
    *) echo "usage: bash $0 [setup|check1|check2|cleanup]" >&2; exit 2 ;;
esac
