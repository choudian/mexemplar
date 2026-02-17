; Mexemplar 安装程序配置
; 需要先安装 Inno Setup: https://jrsoftware.org/isdl.php

#define AppName "Mexemplar"
#define AppVersion "0.1.0"
#define AppPublisher "gaopan"
#define AppExeName "Mexemplar.exe"
#define AppPublisherName "gaopan"

[Setup]
AppId={{A1B2C3D4-E5F6-4A5B-8C7D-9E0F1A2B3C4D}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisherName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=installer
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
WizardImageFile=installer_sidebar.bmp
WizardSmallImageFile=installer_small.bmp
SetupIconFile=src\ui\resources\icons\app_icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
ChangesAssociations=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式:"
Name: "quicklaunchicon"; Description: "创建快速启动快捷方式"; GroupDescription: "附加快捷方式:"; Flags: unchecked

[Files]
Source: "dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "src\recording\browser_extension\*"; DestDir: "{app}\browser_extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "data\*"; DestDir: "{userappdata}\{#AppName}\data"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: quicklaunchicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\{#AppName}"
