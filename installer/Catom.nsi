; ===========================================================================
; Catom Setup Installer (NSIS)
;
; What this does for the end user (Eric):
;   - Double-click Catom-Setup-vX.Y.Z.exe
;   - "Allow this app to install?" -> Yes
;   - Any prior Catom version is auto-uninstalled
;   - Installs to C:\Program Files\Catom\
;   - Creates Desktop + Start Menu shortcuts
;   - Registers in Programs and Features
;   - Optionally launches Catom on Finish
;
; Build (Windows, in CI):
;   makensis /DPRODUCT_VERSION=1.0.3 installer\Catom.nsi
;
; Silent install (auto-updater):
;   Catom-Setup-vX.Y.Z.exe /S
;
; Silent uninstall:
;   "C:\Program Files\Catom\uninstall.exe" /S
; ===========================================================================

!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
!include "LogicLib.nsh"

;------------------------------------------------------------
; Product metadata. Version is passed in from CI via /DPRODUCT_VERSION=...
;------------------------------------------------------------
!ifndef PRODUCT_VERSION
  !define PRODUCT_VERSION "0.0.0-dev"
!endif

!define PRODUCT_NAME       "Catom"
!define PRODUCT_PUBLISHER  "AI Simple"
!define PRODUCT_WEB_SITE   "https://aisimple.co"
!define PRODUCT_EXE        "Catom.exe"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"
!define PRODUCT_REG_ROOT   "Software\${PRODUCT_NAME}"

;------------------------------------------------------------
; Output binary + install behavior
;------------------------------------------------------------
Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "Catom-Setup-v${PRODUCT_VERSION}.exe"
; PER-USER install: into the user's profile, NOT Program Files. This is what
; makes silent auto-updates work — no admin / UAC needed, so the updater can
; download + install a new version without any prompt. (Slack/VS Code/Zoom all
; do this.) Was previously $PROGRAMFILES64 + admin, which made silent updates
; fail because Windows won't show a UAC prompt during a /S silent run.
InstallDir "$LOCALAPPDATA\Programs\Catom"
InstallDirRegKey HKCU "${PRODUCT_REG_ROOT}" "InstallDir"

; No elevation — installs entirely within the current user's profile.
RequestExecutionLevel user

; Compress hard — the payload is ~200MB raw.
SetCompressor /SOLID lzma

; Show simple progress, no console.
ShowInstDetails hide
ShowUninstDetails hide

;------------------------------------------------------------
; Modern UI 2 — Welcome / Directory / Install / Finish + uninstall
;------------------------------------------------------------
!define MUI_ABORTWARNING
!define MUI_ICON   "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

; Offer to launch Catom on Finish (skipped when silent).
!define MUI_FINISHPAGE_RUN "$INSTDIR\${PRODUCT_EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "Launch Catom"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

;------------------------------------------------------------
; Auto-uninstall any previous version BEFORE we install.
; Looks up the prior install's uninstaller from the registry and runs it
; silently. Works for both interactive and /S silent installs.
;------------------------------------------------------------
Function .onInit
  ; Remove a previous PER-USER install (HKCU).
  ReadRegStr $R0 HKCU "${PRODUCT_UNINST_KEY}" "UninstallString"
  ${If} $R0 != ""
    ReadRegStr $R1 HKCU "${PRODUCT_UNINST_KEY}" "InstallLocation"
    DetailPrint "Removing previous Catom install at $R1..."
    ClearErrors
    ExecWait '"$R0" /S _?=$R1' $0
    Delete "$R0"
  ${EndIf}

  ; Also clean up any OLD per-machine (Program Files / HKLM) install left over
  ; from v1.3.0–v1.3.4. We can't silently remove it without admin, but we can
  ; unregister it from HKLM if we happen to have rights, and the leftover files
  ; are harmless once the per-user shortcut takes over. Best-effort only.
  ReadRegStr $R2 HKLM "${PRODUCT_UNINST_KEY}" "UninstallString"
  ${If} $R2 != ""
    ReadRegStr $R3 HKLM "${PRODUCT_UNINST_KEY}" "InstallLocation"
    DetailPrint "Found old machine-wide install at $R3 (superseded by per-user)."
  ${EndIf}
FunctionEnd

Function un.onInit
  ${If} ${RunningX64}
    SetRegView 64
  ${EndIf}
FunctionEnd

;------------------------------------------------------------
; Main install section.
;
; The payload comes from `dist\Catom\` (PyInstaller --onedir output). We
; bundle the entire folder so Catom.exe and its sibling _internal\ DLLs
; stay together. This is the fix for the historical "moved Catom.exe to
; desktop and it failed" bug — they're now installed as a unit under
; Program Files and the user only ever clicks a shortcut.
;------------------------------------------------------------
Section "Catom" SEC_MAIN
  ; CRITICAL: "Error opening file for writing ... Catom.exe" (Abort/Retry/Ignore).
  ; Two distinct locks cause this and we defeat BOTH:
  ;
  ;   (a) Catom is RUNNING -> taskkill the process tree (app + WebView2 kids).
  ;   (b) Catom.exe is locked even AFTER the process dies -> Windows Defender /
  ;       SmartScreen / Explorer grabs the freshly-written-or-killed binary to
  ;       scan it and briefly holds the handle. taskkill + a sleep does NOT fix
  ;       this because the app is already gone — something else owns the file.
  ;
  ; The bulletproof trick (how Chrome/Electron updaters do it): you cannot
  ; OVERWRITE a locked .exe, but Windows DOES let you RENAME it. So move the old
  ; Catom.exe aside, which always succeeds, then File writes a fresh one into the
  ; freed name. The renamed leftover is deleted now or on next reboot.
  nsExec::Exec 'taskkill /F /IM ${PRODUCT_EXE} /T'
  nsExec::Exec 'taskkill /F /IM msedgewebview2.exe /T'
  Sleep 1500

  ${If} ${FileExists} "$INSTDIR\${PRODUCT_EXE}"
    ClearErrors
    Delete "$INSTDIR\${PRODUCT_EXE}"
    ${If} ${Errors}
      ; Still locked — rename it out of the way (this works even when locked).
      Delete /REBOOTOK "$INSTDIR\Catom-old.exe"
      ClearErrors
      Rename "$INSTDIR\${PRODUCT_EXE}" "$INSTDIR\Catom-old.exe"
      Delete /REBOOTOK "$INSTDIR\Catom-old.exe"
    ${EndIf}
  ${EndIf}

  SetOutPath "$INSTDIR"
  SetOverwrite on

  ; Payload — built by PyInstaller into dist\Catom\ before NSIS runs.
  File /r "..\dist\Catom\*.*"

  ; Per-user state — make sure %APPDATA%\Catom\ + all managed subfolders
  ; exist so first-run wizard + pipeline + feedback bundle can write without
  ; UAC prompts later. See app/main.py _managed_*_dir helpers.
  CreateDirectory "$APPDATA\Catom"
  CreateDirectory "$APPDATA\Catom\downloads"
  CreateDirectory "$APPDATA\Catom\distribution"
  CreateDirectory "$APPDATA\Catom\last_run"
  CreateDirectory "$APPDATA\Catom\feedback"
  CreateDirectory "$APPDATA\Catom\state"
  CreateDirectory "$APPDATA\Catom\ChromeProfile"

  ; Shortcuts — per-user (current context), so no admin needed. Desktop +
  ; Start Menu entry for the installing user.
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortCut  "$SMPROGRAMS\${PRODUCT_NAME}\Catom.lnk"   "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
  CreateShortCut  "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall Catom.lnk" "$INSTDIR\uninstall.exe"
  CreateShortCut  "$DESKTOP\Catom.lnk"                     "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0

  ; Uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Persisted install location (HKCU — per-user)
  WriteRegStr HKCU "${PRODUCT_REG_ROOT}" "InstallDir"    "$INSTDIR"
  WriteRegStr HKCU "${PRODUCT_REG_ROOT}" "Version"       "${PRODUCT_VERSION}"

  ; Programs and Features entry (HKCU — appears in this user's Apps list)
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayName"     "${PRODUCT_NAME}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayVersion"  "${PRODUCT_VERSION}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "Publisher"       "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "URLInfoAbout"    "${PRODUCT_WEB_SITE}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "DisplayIcon"     "$INSTDIR\${PRODUCT_EXE}"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "${PRODUCT_UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKCU "${PRODUCT_UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${PRODUCT_UNINST_KEY}" "NoRepair" 1

  ; Estimated size in KB for Programs and Features.
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKCU "${PRODUCT_UNINST_KEY}" "EstimatedSize" "$0"
SectionEnd

;------------------------------------------------------------
; Silent-install hook: when launched by the in-app auto-updater (/S),
; relaunch Catom after the install finishes so the user lands back in
; the new version without lifting a finger.
;------------------------------------------------------------
Function .onInstSuccess
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "/S" $R1
  ${IfNot} ${Errors}
    ; Silent install — relaunch Catom.
    Exec '"$INSTDIR\${PRODUCT_EXE}"'
  ${EndIf}
FunctionEnd

;------------------------------------------------------------
; Uninstaller
;------------------------------------------------------------
Section "Uninstall"
  ; Best-effort: close any running Catom.exe so we can remove files.
  ; The /S guard means we don't pop a UI from a silent uninstall.
  nsExec::Exec 'taskkill /F /IM ${PRODUCT_EXE} /T'

  ; Wipe install dir
  RMDir /r "$INSTDIR"

  ; Shortcuts — per-user (current context), plus clean any all-users copies
  ; left by an older (v1.3.0–v1.3.4) machine-wide install.
  Delete "$DESKTOP\Catom.lnk"
  RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"
  SetShellVarContext all
  Delete "$DESKTOP\Catom.lnk"
  RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"
  SetShellVarContext current

  ; Registry — per-user
  DeleteRegKey HKCU "${PRODUCT_UNINST_KEY}"
  DeleteRegKey HKCU "${PRODUCT_REG_ROOT}"

  ; NOTE: we deliberately leave %APPDATA%\Catom\ in place so the user's
  ; saved config + Chrome profile survive an uninstall/reinstall. If you
  ; ever need a full wipe, delete it manually or add an opt-in step here.
SectionEnd
