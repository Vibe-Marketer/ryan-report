#!/bin/bash
# Catom Cleanup — Run before installing a new version.
# Removes ALL previous app copies, settings, caches, and artifacts.

echo "Cleaning up all previous Catom installations..."

# Kill any running instances
killall Catom 2>/dev/null
killall "Google Chrome" 2>/dev/null
sleep 1

# Remove app from Applications
rm -rf /Applications/Catom.app 2>/dev/null

# Find and remove ANY Catom.app copies anywhere in user folders
find ~/Desktop -maxdepth 2 -name "Catom.app" -type d -exec rm -rf {} + 2>/dev/null
find ~/Downloads -maxdepth 2 -name "Catom.app" -type d -exec rm -rf {} + 2>/dev/null
find ~/Documents -maxdepth 2 -name "Catom.app" -type d -exec rm -rf {} + 2>/dev/null
find /private/tmp -maxdepth 3 -name "Catom.app" -type d -exec rm -rf {} + 2>/dev/null

# Clear ALL user data
rm -rf ~/Library/Application\ Support/Catom 2>/dev/null
rm -rf ~/Library/WebKit/Catom 2>/dev/null
rm -rf ~/Library/Caches/Catom 2>/dev/null
rm -rf ~/Library/Caches/com.andrewnaegele.catom 2>/dev/null
rm -rf ~/Library/Saved\ Application\ State/com.andrewnaegele.catom.savedState 2>/dev/null
rm -rf ~/Library/Preferences/com.andrewnaegele.catom.plist 2>/dev/null
rm -rf ~/Library/HTTPStorages/com.andrewnaegele.catom 2>/dev/null
rm -rf ~/Library/LaunchAgents/com.andrewnaegele.catom.plist 2>/dev/null

# Remove package receipts
pkgutil --forget com.andrewnaegele.catom 2>/dev/null

# Empty Trash of any Catom copies
find ~/.Trash -maxdepth 1 -name "Catom*" -exec rm -rf {} + 2>/dev/null

echo "Done. You can now install Catom.pkg."
