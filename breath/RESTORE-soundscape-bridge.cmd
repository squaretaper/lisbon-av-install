# To return the strips to Pablo's audio-reactive bridge:
pkill -f breath_clock.py
launchctl load ~/Library/LaunchAgents/ai.ganchitecture.lisbon-esp32-sync.plist
# (launchd auto-restarts the soundscape bridge on the serial port)
