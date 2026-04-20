## ADDED Requirements

### Requirement: Hook captures screenshots on mouse left click and Enter key
The system SHALL use pynput mouse and keyboard listeners to detect mouse left button clicks (mousedown) and Enter key presses (keydown). Upon detection, the system SHALL enqueue a before CaptureTask within 1ms and schedule an after CaptureTask after a configurable delay (default 0.2s). The system SHALL NOT capture screenshots for mouse movement, scroll, right/middle click, or non-Enter keyboard events.

#### Scenario: Mouse left click triggers before and after screenshots
- **WHEN** a mouse left button mousedown event is detected during recording
- **THEN** a before CaptureTask is enqueued immediately, and an after CaptureTask is scheduled after the configured delay

#### Scenario: Enter key triggers before and after screenshots
- **WHEN** an Enter keydown event is detected during recording
- **THEN** a before CaptureTask is enqueued immediately, and an after CaptureTask is scheduled after the configured delay

#### Scenario: Non-target events are ignored
- **WHEN** mouse movement, scroll, right click, middle click, or non-Enter keyboard events occur during recording
- **THEN** no CaptureTask is enqueued and no screenshot is captured

### Requirement: FrameSampler continuously samples browser frames
A _FrameSampler background thread SHALL run at approximately 100ms intervals, locating the browser foreground HWND via _BrowserHwndLocator, capturing the window via mss, and appending _FrameSample entries to a _FrameRingBuffer. The ring buffer SHALL hold at most 64 samples (~6.4s at 100ms interval), discarding the oldest when full.

#### Scenario: Browser in foreground during sampling
- **WHEN** the _FrameSampler thread runs and the browser window is in the foreground
- **THEN** a _FrameSample with the current timestamp and JPEG bytes is appended to the ring buffer

#### Scenario: Browser not in foreground during sampling
- **WHEN** the _FrameSampler thread runs but the browser is not in the foreground
- **THEN** no sample is added to the ring buffer; the thread continues at the next interval

#### Scenario: Ring buffer at capacity
- **WHEN** the ring buffer already contains 64 samples and a new sample is appended
- **THEN** the oldest sample is automatically discarded (deque maxlen behavior)

### Requirement: FrameRingBuffer provides timestamp-based frame lookup
The _FrameRingBuffer SHALL provide `latest_before(ts, max_age)` to find the most recent frame at or before a given timestamp within max_age seconds, and `earliest_after(ts, max_lag)` to find the earliest frame at or after a given timestamp within max_lag seconds. It SHALL also provide `latest_recent(max_age)` as a fallback for the nearest recent frame. All lookups SHALL be thread-safe.

#### Scenario: Before frame found in buffer
- **WHEN** _ScreenCapturer processes a before task and the ring buffer contains a frame within 1.0s before the event timestamp
- **THEN** that buffered frame is used instead of performing a live capture

#### Scenario: After frame found in buffer
- **WHEN** _ScreenCapturer processes an after task and the ring buffer contains a frame within 2.0s after (event_ts + after_delay × 0.5)
- **THEN** that buffered frame is used instead of performing a live capture

#### Scenario: No buffered frame available — fallback to live capture
- **WHEN** the ring buffer has no matching frame for the requested timestamp window
- **THEN** _ScreenCapturer falls back to live capture (HWND locate → mss grab → crop → encode)

### Requirement: Hook callback returns within 1ms
The pynput hook callback SHALL only generate a CaptureTask dataclass and enqueue it to the capture worker thread queue. The callback SHALL NOT call mss, Pillow, or any Win32 API directly. This ensures the Windows global hook proc returns fast enough to avoid LowLevelHooksTimeout.

#### Scenario: Callback completes within 1ms
- **WHEN** a target input event triggers the hook callback
- **THEN** the callback returns in under 1ms by only enqueuing a CaptureTask without performing I/O or screenshot operations

### Requirement: ScreenCapturer worker thread performs async capture
The _ScreenCapturer worker thread SHALL pull CaptureTasks from the queue, attempt to find a matching frame from the _FrameRingBuffer first, and only fall back to live capture (HWND locate → mss grab → crop → JPEG encode) if no buffered frame is available. The thread SHALL handle all errors gracefully by writing skipped records instead of crashing.

#### Scenario: Successful screenshot capture
- **WHEN** a CaptureTask is dequeued and the browser window is in the foreground
- **THEN** the worker grabs the screen, crops to the browser window rectangle, encodes as JPEG with configurable quality (default 85), and writes the record to the screenshots queue file

#### Scenario: Browser not in foreground
- **WHEN** a CaptureTask is dequeued but GetForegroundWindow() does not belong to the Chromium candidate set
- **THEN** the worker writes a skipped record with skipped_reason="not_foreground" and no data_b64

#### Scenario: Capture fails with mss exception
- **WHEN** mss.grab() throws an exception during capture
- **THEN** the worker logs a warning and writes a skipped record with skipped_reason="capture_failed"

### Requirement: BrowserHwndLocator finds foreground Chromium window
The _BrowserHwndLocator SHALL maintain a candidate set of Chromium top-level windows (class `Chrome_WidgetWin_1`) belonging to the browser PID and its child processes. On each capture, it SHALL check if GetForegroundWindow() belongs to the candidate set. If yes, it returns that HWND; otherwise returns None (not_foreground).

#### Scenario: Browser window is foreground
- **WHEN** the foreground window belongs to the Chromium candidate set
- **THEN** the locator returns the foreground HWND for screenshot cropping

#### Scenario: Browser window is not foreground
- **WHEN** the foreground window does not belong to the Chromium candidate set
- **THEN** the locator returns None and the screenshot is skipped with reason "not_foreground"

#### Scenario: Candidate set refreshes on each capture
- **WHEN** a capture is requested
- **THEN** the locator re-scans via EnumWindows to discover new windows, with O(1) IsWindow validity checks on existing candidates

### Requirement: Capture queue applies bounded backpressure
The _ScreenCapturer task queue SHALL be bounded with `maxsize=50`. When the queue is full, the system SHALL drop the oldest `moment=before` task from the queue (scan and remove one entry) before enqueuing the new task, and emit `log.warning("capture queue saturated, dropping oldest before task")`. If the queue contains no `moment=before` entries (all pending tasks are `moment=after`), the system SHALL discard the newly-incoming task instead, preserving all `after` tasks. Dropped tasks SHALL NOT be written to the screenshots queue file (no record left, log-only diagnostic).

#### Scenario: Drop oldest before task when queue is full
- **WHEN** the capture queue is at maxsize=50 and the queue contains at least one `moment=before` task
- **THEN** the oldest `moment=before` task is removed from the queue, a warning is logged, and the new task is enqueued

#### Scenario: Queue all-after preserves after tasks
- **WHEN** the capture queue is at maxsize=50 and all pending tasks are `moment=after`
- **THEN** the newly-incoming task is discarded with a warning, and existing `after` tasks remain in the queue unaffected

#### Scenario: Dropped tasks leave no trace in queue file
- **WHEN** a capture task is dropped due to backpressure
- **THEN** no record is written to the screenshots queue file; the drop is only visible in logs

### Requirement: AfterScheduler uses heapq for efficient scheduling
The _AfterScheduler SHALL use a heapq-based priority queue to schedule after screenshots, avoiding per-action Timer threads. On stop(), it SHALL flush all pending after tasks within the flush timeout (default 3s).

#### Scenario: After screenshot scheduled after delay
- **WHEN** a before capture is triggered by an input event
- **THEN** an after CaptureTask is scheduled after the configured delay (default 0.2s) via the heapq scheduler

#### Scenario: Stop flushes pending after tasks
- **WHEN** hook.stop() is called with pending after tasks
- **THEN** the scheduler waits up to flush_timeout (3s) for pending tasks to complete, then discards remaining tasks with a warning

### Requirement: QueueWriter writes JSONL with independent lock
The _QueueWriter SHALL write screenshot records to the screenshots queue file as JSONL, using an independent threading.Lock that is NOT shared with the actions queue write lock. Each record SHALL contain: recording_id, capture_id, moment, source_trigger, input_started_at, input_completed_at, captured_at, data_b64 (or null for skipped), media_type (or null), skipped_reason (or null).

#### Scenario: Successful screenshot record written
- **WHEN** a screenshot is successfully captured and encoded
- **THEN** a JSONL record with all fields is written, including data_b64 with JPEG base64 and media_type="image/jpeg"

#### Scenario: Skipped screenshot record written
- **WHEN** a screenshot is skipped due to not_foreground or other reason
- **THEN** a JSONL record is written with skipped_reason set and no data_b64/media_type fields

### Requirement: Hook degrades gracefully on non-Windows or missing dependencies
The BrowserScreenshotHook.start() SHALL return False (not raise) on non-Windows platforms, when pynput/mss/Pillow are unavailable, or when Win32 initialization fails. The calling code SHALL log a warning and continue recording without screenshots.

#### Scenario: Non-Windows platform
- **WHEN** BrowserScreenshotHook.start() is called on a non-Windows platform
- **THEN** start() returns False and the browser recording continues without screenshots

#### Scenario: Missing pynput dependency
- **WHEN** BrowserScreenshotHook.start() is called but pynput is not installed
- **THEN** start() returns False with a warning log, and recording continues normally

### Requirement: Platform imports are deferred
The module top-level SHALL only contain stdlib constants, type definitions, and lightweight helpers. All platform-specific imports (pynput, mss, PIL, ctypes.windll) SHALL be deferred to inside start() or Windows-only helper functions.

#### Scenario: Import on Linux does not touch Win32
- **WHEN** the module is imported on Linux
- **THEN** no Win32 API calls or pynput/mss imports occur at module level

### Requirement: DPI awareness is set at application entry point
The application entry point (main.py) SHALL call SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2) before constructing QApplication. If that fails, it SHALL fallback to SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE), then SetProcessDPIAware(). The BrowserScreenshotHook SHALL NOT modify process DPI awareness.

#### Scenario: DPI awareness set before QApplication
- **WHEN** the application starts on Windows
- **THEN** Per-Monitor V2 DPI awareness is set before QApplication construction, and Hook only performs read-only DPI detection

#### Scenario: DPI awareness fallback chain
- **WHEN** SetProcessDpiAwarenessContext fails
- **THEN** the system falls back to SetProcessDpiAwareness, then SetProcessDPIAware, without crashing
