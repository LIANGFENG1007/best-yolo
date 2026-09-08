#define AppVersion GetEnv("BEST_YOLO_VERSION")
#define SourceDir GetEnv("BEST_YOLO_SOURCE_DIR")
#define OutputDir GetEnv("BEST_YOLO_OUTPUT_DIR")
#define SetupIcon GetEnv("BEST_YOLO_SETUP_ICON")
#define VCRedist GetEnv("BEST_YOLO_VC_REDIST")
#define ChineseMessages GetEnv("BEST_YOLO_INNO_CHINESE")

[Setup]
AppId={{C2EFD6F0-D3F8-4F5B-87B2-D9A26CF39E4F}
AppName=Best yolo
AppVersion={#AppVersion}
AppVerName=Best yolo {#AppVersion}
AppPublisher=LIANGFENG1007
AppPublisherURL=https://github.com/LIANGFENG1007/best-yolo
AppSupportURL=https://github.com/LIANGFENG1007/best-yolo/issues
AppUpdatesURL=https://github.com/LIANGFENG1007/best-yolo/releases/latest
DefaultDirName={autopf}\Best yolo
DisableDirPage=no
DefaultGroupName=Best yolo
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=BestYolo-Setup-{#AppVersion}-win64
SetupIconFile={#SetupIcon}
UninstallDisplayIcon={app}\BestYolo.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany=LIANGFENG1007
VersionInfoDescription=Best yolo Windows 安装程序
VersionInfoProductName=Best yolo
VersionInfoProductVersion={#AppVersion}
VersionInfoCopyright=Copyright (C) 2026 LIANGFENG1007

[Languages]
Name: "chinesesimplified"; MessagesFile: "{#ChineseMessages}"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#VCRedist}"; DestDir: "{tmp}"; DestName: "VC_redist.x64.exe"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\Best yolo"; Filename: "{app}\BestYolo.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Best yolo"; Filename: "{app}\BestYolo.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\VC_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "正在安装 Microsoft Visual C++ 运行库..."; Flags: runhidden waituntilterminated
Filename: "{app}\BestYolo.exe"; Description: "启动 Best yolo"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
