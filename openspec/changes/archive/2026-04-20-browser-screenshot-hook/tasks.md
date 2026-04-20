## 0. Pre-Implementation Verification

- [x] 0.1 Grep `docs/PROJECT_CONSTRAINTS.md` for `analyze_image` / `Repository` to confirm the Repository-pattern exemption for `_analyze_image` exists (referenced in §八 file list). If NOT found, update the plan: either add the exemption clause to PROJECT_CONSTRAINTS.md before proceeding, OR add proper query methods to RecordingRepository instead of letting `_analyze_image` call `DuckDBManager.fetchone()` directly
- [x] 0.2 Inspect `DuckDBManager._VALID_TABLES` / `_VALID_COLUMNS` current data structure shape (`{'table': set(cols)}` vs list-of-dict vs other) by reading the file directly; match the existing `_migrate_*` style when registering `recording_screenshots`. Document the actual shape in task 1.2 before touching the file.

## 1. Infrastructure & Schema

- [x] 1.1 Create `src/recording/queue_paths.py` with get_recording_queue_dir(), get_recording_actions_queue_path(), get_recording_screenshots_queue_path(), delete_queue_file()
- [x] 1.2 Add `recording_screenshots` table + sequence + `(recording_id, moment, timestamp)` 复合索引 to DuckDBManager; update _VALID_TABLES / _VALID_COLUMNS (verified existing metadata shape before edit: `_VALID_TABLES` is a `frozenset`, `_VALID_COLUMNS` is a `dict[str, frozenset]`)
- [x] 1.3 Register `recording_screenshots` in recording_data_tools._COMMON_TABLES metadata
- [x] 1.4 Add insert_screenshot_batch() to RecordingRepository with epoch→UTC timestamp conversion

## 2. Screenshot Queue Parser

- [x] 2.1 Create `src/recording/browser/screenshot_queue_parser.py` with ScreenshotRow dataclass, iter_screenshots_queue(), batch_insert_screenshots()

## 3. Browser PID Resolution

- [x] 3.1 Add resolve_browser_pid() to PlaywrightRecordingDriver: psutil scan + bundle path match + --type= filter + multi-candidate safe degradation

## 4. BrowserScreenshotHook Module

- [x] 4.1 Create `src/recording/browser_screenshot_hook.py` with BrowserScreenshotHook class interface (start/stop)
- [x] 4.2 Implement _BrowserHwndLocator: EnumWindows candidate set, foreground HWND selection, Chrome_WidgetWin_1 class filter
- [x] 4.3 Implement _ScreenCapturer worker thread: queue pull → buffer lookup (latest_before / earliest_after) → fallback HWND locate → mss grab → DwmGetWindowAttribute 优先 HWND crop → JPEG encode → write queue; task queue uses custom _CaptureTaskQueue (deque + Condition, maxsize=50); on full, drop oldest `moment=before` task (or the new task if queue is all-after) with log.warning
- [x] 4.3a Implement frame sampling as _ScreenCapturer._run_sampler() background thread (非独立类): 100ms interval continuous sampling → _FrameRingBuffer (64 frames, ~6.4s); browser not foreground → skip; thread-safe ring buffer with deque(maxlen=64); _FrameSample dataclass 封装帧数据
- [x] 4.3b Implement _FrameRingBuffer: latest_before(ts, max_age=1.0s), earliest_after(ts, max_lag=2.0s), latest_recent(max_age=2.0s) lookups; thread-safe via threading.Lock
- [x] 4.4 Implement _AfterScheduler: heapq-based after screenshot scheduling
- [x] 4.5 Implement _QueueWriter: JSONL write with independent lock
- [x] 4.6 Implement _CaptureIdGenerator: monotonic counter (cap_0001)
- [x] 4.7 Add DPI detection (read-only) in Hook: Per-Monitor / System Aware / Unaware coordinate strategy selection
- [x] 4.8 Add platform isolation: deferred imports, non-Windows graceful degradation (start() returns False)

## 5. DPI Awareness at Application Entry

- [x] 5.1 Add Per-Monitor V2 DPI awareness setting in main.py before QApplication construction, with fallback chain

## 6. Persister Integration

- [x] 6.1 Modify DuckDBRecordingPersister.save_to_duckdb(): wrap actions INSERT + screenshots INSERT in a single DuckDB transaction (BEGIN/COMMIT); on any DB exception ROLLBACK and preserve both queue files; on commit success delete both queue files. Row-level graceful skip inside iter_screenshots_queue does NOT trigger transaction failure.

## 7. analyze_image Tool Overhaul

- [x] 7.1 Rewrite _analyze_image: fetch action.timestamp → time-window query on recording_screenshots (WINDOW_BEFORE=1.0, WINDOW_BEFORE_FORWARD_SLACK=0.25, WINDOW_AFTER=1.5), remove old SELECT screenshot_before/after path

## 8. BrowserRecorder Wire-up

- [x] 8.1 Add _last_browser_action_ts field to BrowserRecorder; update it in _emit_browser_action before on_action callback check
- [x] 8.2 Add _wait_for_stop_drain() async method: poll _last_browser_action_ts with 250ms quiet / 1s max timeout
- [x] 8.3 Wire hook in _async_start_recording: resolve_browser_pid → BrowserScreenshotHook.start() → degrade on False
- [x] 8.4 Rewrite _async_stop_recording order: send_stop → drain → gate_ingress → hook.stop(flush 3s) → close_browser → cleanup_dirs → save_to_duckdb → cleanup queues
- [x] 8.5 Replace BrowserRecorder queue path construction with queue_paths helper

## 9. Recovery Adjustment

- [x] 9.1 Replace hardcoded queue dir in RecordingRecovery with queue_paths.get_recording_queue_dir()
- [x] 9.2 Change startup scan to always check queue directory (not only on WAL abnormal)
- [x] 9.3 Add orphan *_screenshots.jsonl cleanup logic: log.warning + delete

## 10. Tests

- [x] 10.1 Test iter_screenshots_queue: base64 decode, skipped rows; malformed JSON line / missing required field / base64 decode failure → log.warning + continue to next line, iterator does NOT raise
- [x] 10.2 Test batch_insert_screenshots: skipped filter, batch insert, source_trigger passthrough
- [x] 10.3 Test _analyze_image time-window query: before/after windows, ORDER BY nearest, no source_trigger in WHERE, multi-screenshot LIMIT 1
- [x] 10.4 Test resolve_browser_pid: bundle path match, --type= filter, shared profile excluded, multi-candidate degradation
- [x] 10.5 Test queue_paths: consistent dir between BrowserRecorder and Recovery
- [x] 10.6 Test persister screenshot insert: actions+screenshots in one DuckDB transaction (commit → delete both queues; any DB exception → ROLLBACK + preserve both queues); row-level skip inside iter_screenshots_queue does NOT trigger rollback; missing screenshots queue tolerated
- [x] 10.7 Test screenshots queue lifecycle: success delete, failure preserve, orphan cleanup on startup
- [x] 10.8 Test recording_screenshots table creation: idempotent CREATE IF NOT EXISTS
- [x] 10.9 Test metadata registration: _VALID_TABLES / _VALID_COLUMNS / _COMMON_TABLES include recording_screenshots
- [x] 10.10 Architecture wiring smoke tests + guard tests (stop order, no old SQL patterns, no pair/match references)
- [x] 10.11 Test _ScreenCapturer queue backpressure: maxsize=50; when full, drop oldest `moment=before` task with log.warning; `moment=after` tasks retained; when queue is all-after, drop new incoming task
- [x] 10.11a Test _FrameRingBuffer: latest_before / earliest_after / latest_recent lookups return correct frames; max_age / max_lag filtering; empty buffer returns None; thread-safe concurrent append + lookup
- [x] 10.12 Test save_to_duckdb transaction atomicity: DB exception during screenshots INSERT rolls back actions INSERT; both queue files preserved after rollback
