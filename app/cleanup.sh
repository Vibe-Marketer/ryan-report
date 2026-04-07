#!/bin/bash
# Catom Cleanup — Run before installing a new version.
# Removes all previous app copies, settings, and caches.

echo "Cleaning up previous Catom installation..."

# Remove app from Applications
rm -rf /Applications/Catom.app 2>/dev/null

# Remove any stale copies
rm -rf ~/Desktop/Catom.app 2>/dev/null
rm -rf ~/Downloads/Catom.app 2>/dev/null

# Clear user config, Chrome automation profile, and caches
rm -rf ~/Library/Application\ Support/Catom 2>/dev/null
rm -rf ~/Library/WebKit/Catom 2>/dev/null
rm -rf ~/Library/Caches/Catom 2>/dev/null
rm -rf ~/Library/Saved\ Application\ State/com.andrewnaegele.catom.savedState 2>/dev/null
rm -rf ~/Library/Preferences/com.andrewnaegele.catom.plist 2>/dev/null

# Remove package receipt
pkgutil --forget com.andrewnaegele.catom 2>/dev/null

echo "Done. You can now install the new Catom.pkg."
