## ADDED Requirements

### Requirement: resolve_browser_pid finds Chromium main process via bundle path
PlaywrightRecordingDriver SHALL provide a resolve_browser_pid() method that scans running processes via psutil to find the Chromium main browser process launched by the current Playwright session. The primary matching criterion SHALL be the presence of the Playwright extension bundle path (`--load-extension=.../<launch_token>`) in the process command line.

#### Scenario: Single matching browser process found
- **WHEN** exactly one Chromium process matches the extension bundle path and has no --type= parameter
- **THEN** resolve_browser_pid() returns that process's PID

#### Scenario: No matching process found
- **WHEN** no Chromium process contains the current session's extension bundle path
- **THEN** resolve_browser_pid() returns None and no screenshots are captured

### Requirement: Subprocesses filtered via --type= parameter
The PID resolution SHALL exclude processes whose command line contains `--type=` (renderer, gpu-process, utility, etc.). Only the main browser process without `--type=` SHALL be considered as a candidate.

#### Scenario: Renderer subprocess excluded
- **WHEN** a Chromium process has --type=renderer in its command line but also contains the bundle path
- **THEN** that process is excluded from candidates

#### Scenario: Multiple --type= processes all excluded
- **WHEN** multiple Chromium child processes (--type=renderer, --type=gpu-process, etc.) are found
- **THEN** all are excluded and only the main browser process is considered

### Requirement: Process name filtered to Chromium family
The PID resolution SHALL only consider processes whose name belongs to the Chromium family: chrome.exe, chromium.exe, msedge.exe, and similar variants. Other process names SHALL be ignored.

#### Scenario: Chrome process matched
- **WHEN** a process named chrome.exe has the bundle path in its command line
- **THEN** it is included as a candidate

#### Scenario: Edge process matched
- **WHEN** a process named msedge.exe has the bundle path in its command line
- **THEN** it is included as a candidate

### Requirement: Multiple candidates cause safe degradation
When multiple candidate processes pass all filters (after excluding --type= subprocesses), resolve_browser_pid() SHALL return None rather than risking binding to the wrong process. The recording SHALL continue without screenshots.

#### Scenario: Multiple main browser processes found
- **WHEN** two or more Chromium main processes match the bundle path
- **THEN** resolve_browser_pid() returns None and logs a warning about ambiguous PID resolution

### Requirement: Shared persistent profile is not used as fallback
The default shared `playwright_user_data_persistent` directory SHALL NOT be used as a PID matching criterion. Only session-unique identifiers (extension bundle path, or user_data_dir with unique suffix when persistent=False) MAY be used as fallback, and only with strict uniqueness validation.

#### Scenario: Shared persistent profile ignored for PID matching
- **WHEN** the only match is via a shared persistent profile directory
- **THEN** resolve_browser_pid() returns None rather than risking false positive

#### Scenario: Session-unique user_data_dir as fallback
- **WHEN** persistent=False and the user_data_dir contains a session-unique suffix
- **THEN** the user_data_dir MAY be used as a secondary matching criterion with strict validation
