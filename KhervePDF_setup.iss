; Inno Setup script for KhervePDF.
;
; Produces a single Setup_KhervePDF_<version>.exe installer that drops
; the one-folder PyInstaller build under Program Files\KhervePDF and
; wires up a Start-menu entry, optional desktop icon, .pdf association,
; and an uninstaller.
;
; Build steps:
;   1. pip install -r requirements.txt
;   2. pip install pyinstaller
;   3. pyinstaller KhervePDF.spec --noconfirm
;   4. ISCC.exe KhervePDF_setup.iss
;      (Inno Setup 6 — https://jrsoftware.org/isinfo.php)
;
; Output lands in .\installer\.

#define MyAppName        "KhervePDF"
#define MyAppPublisher   "Gwilherm Kerherve"
#define MyAppExeName     "KhervePDF.exe"
#define MyAppVersion     "0.66"

[Setup]
; Globally-unique app ID — keeps the uninstaller info tidy and lets
; users in-place upgrade without leaving stale entries.
AppId={{F2A3C1E4-9B7E-4D55-A8F1-2C6E9B0D4A12}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Default install target: Program Files (autopf picks the right
; "Program Files" or "Program Files (x86)" based on 64/32-bit).
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
; Need admin to write under Program Files. The override dialog lets
; the user fall back to a per-user install if they want to.
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=installer
OutputBaseFilename=Setup_KhervePDF_{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=LICENSE
; Setup wizard icon — same red KP monogram baked into the .exe.
; build_release.ps1 / KhervePDF.spec produces this from
; tools/generate_icon.py.
SetupIconFile=build\KhervePDF.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "fileassoc_pdf"; Description: "Open .pdf files with {#MyAppName}"; GroupDescription: "File associations:"; Flags: unchecked

[Files]
; Sweep the entire PyInstaller dist folder — bootloader + _internal
; with all the bundled wheels (PyMuPDF, pyHanko / cryptography stack,
; PySide6, pygit2, pikepdf, qtawesome, etc.).
Source: "dist\KhervePDF\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}";              Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}";    Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}";        Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Optional .pdf association — only writes when the user ticks the
; corresponding task. Uses Open With → "KhervePDF" rather than
; taking over the default handler.
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "KhervePDF.Document"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc_pdf
Root: HKA; Subkey: "Software\Classes\KhervePDF.Document"; ValueType: string; ValueData: "KhervePDF Document"; Flags: uninsdeletekey; Tasks: fileassoc_pdf
Root: HKA; Subkey: "Software\Classes\KhervePDF.Document\DefaultIcon"; ValueType: string; ValueData: "{app}\{#MyAppExeName},0"; Tasks: fileassoc_pdf
Root: HKA; Subkey: "Software\Classes\KhervePDF.Document\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: fileassoc_pdf
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
