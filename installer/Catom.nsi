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
InstallDir "$PROGRAMFILES64\Catom"
InstallDirRegKey HKLM "${PRODUCT_REG_ROOT}" "InstallDir"

; Need admin to write to Program Files + HKLM.
RequestExecutionLevel admin

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
  ; Force x64 install location even when launched from a 32-bit shim.
  ${If} ${RunningX64}
    SetRegView 64
  ${EndIf}

  ReadRegStr $R0 HKLM "${PRODUCT_UNINST_KEY}" "UninstallString"
  ${If} $R0 != ""
    ReadRegStr $R1 HKLM "${PRODUCT_UNINST_KEY}" "InstallLocation"
    DetailPrint "Removing previous Catom install at $R1..."
    ; _?=$R1 keeps the uninstaller running from its current location so
    ; it can delete itself; /S = silent. Wait for completion.
    ClearErrors
    ExecWait '"$R0" /S _?=$R1' $0
    ${If} ${Errors}
      DetailPrint "Previous-version uninstaller errored (continuing anyway)."
    ${EndIf}
    ; ExecWait with _?= leaves the old uninstall.exe behind — clean it up.
    Delete "$R0"
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

  ; Shortcuts — all-users so they appear for every account on the machine
  ; AND so the Start Menu entry lands in the common Programs folder (an admin
  ; install otherwise writes shortcuts to the installing user's profile only,
  ; which is why v1.3.0 had a Desktop icon but no All-Users Start Menu entry).
  ; Managed %APPDATA%\Catom dirs above stay per-user (default context); only
  ; the shortcuts switch to all-users.
  SetShellVarContext all
  CreateDirectory "$SMPROGRAMS\${PRODUCT_NAME}"
  CreateShortCut  "$SMPROGRAMS\${PRODUCT_NAME}\Catom.lnk"   "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
  CreateShortCut  "$SMPROGRAMS\${PRODUCT_NAME}\Uninstall Catom.lnk" "$INSTDIR\uninstall.exe"
  CreateShortCut  "$DESKTOP\Catom.lnk"                     "$INSTDIR\${PRODUCT_EXE}" "" "$INSTDIR\${PRODUCT_EXE}" 0
  SetShellVarContext current

  ; Uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"

  ; Persisted install location
  WriteRegStr HKLM "${PRODUCT_REG_ROOT}" "InstallDir"    "$INSTDIR"
  WriteRegStr HKLM "${PRODUCT_REG_ROOT}" "Version"       "${PRODUCT_VERSION}"

  ; Programs and Features entry
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName"     "${PRODUCT_NAME}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion"  "${PRODUCT_VERSION}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher"       "${PRODUCT_PUBLISHER}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "URLInfoAbout"    "${PRODUCT_WEB_SITE}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon"     "$INSTDIR\${PRODUCT_EXE}"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
  WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoRepair" 1

  ; Estimated size in KB for Programs and Features.
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "EstimatedSize" "$0"
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

  ; Shortcuts — match the all-users context they were created with, plus
  ; clean any stray per-user copies left by an older (v1.3.0) install.
  SetShellVarContext all
  Delete "$DESKTOP\Catom.lnk"
  RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"
  SetShellVarContext current
  Delete "$DESKTOP\Catom.lnk"
  RMDir /r "$SMPROGRAMS\${PRODUCT_NAME}"

  ; Registry
  DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"
  DeleteRegKey HKLM "${PRODUCT_REG_ROOT}"

  ; NOTE: we deliberately leave %APPDATA%\Catom\ in place so the user's
  ; saved config + Chrome profile survive an uninstall/reinstall. If you
  ; ever need a full wipe, delete it manually or add an opt-in step here.
SectionEnd
