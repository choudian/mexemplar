## ADDED Requirements

### Requirement: Screenshots stored in independent recording_screenshots table
The system SHALL create a `recording_screenshots` DuckDB table with columns: screenshot_id (PK auto-increment), recording_id, moment ('before'|'after'), timestamp, capture_id (nullable), source_trigger (nullable), input_started_at (nullable), input_completed_at (nullable), media_type, data (BLOB). The table SHALL be created with CREATE TABLE IF NOT EXISTS for idempotent migration.

#### Scenario: Table creation on fresh database
- **WHEN** DuckDB is initialized and the recording_screenshots table does not exist
- **THEN** the table is created with all specified columns and the recording_screenshot_id_seq sequence

#### Scenario: Table already exists
- **WHEN** DuckDB is initialized and the recording_screenshots table already exists
- **THEN** no error occurs and the existing table is used as-is

### Requirement: analyze_image uses time-window query on recording_screenshots
The `_analyze_image` tool SHALL query `recording_screenshots` by action timestamp with time windows, NOT by sequence_number on the actions table. For each action index, it SHALL fetch the action's timestamp from the actions table, then query recording_screenshots for the nearest before screenshot within [T - WINDOW_BEFORE, T + WINDOW_BEFORE_FORWARD_SLACK] and the nearest after screenshot within [T, T + WINDOW_AFTER]. The query WHERE clause SHALL NOT include source_trigger or capture_id.

#### Scenario: Before screenshot found within time window
- **WHEN** analyze_image queries for a before screenshot with WINDOW_BEFORE=1.0s and WINDOW_BEFORE_FORWARD_SLACK=0.25s
- **THEN** the nearest before screenshot by timestamp is returned, ordered by abs(epoch difference)

#### Scenario: After screenshot found within time window
- **WHEN** analyze_image queries for an after screenshot with WINDOW_AFTER=1.5s
- **THEN** the nearest after screenshot within [T, T+1.5s] is returned

#### Scenario: No screenshot within time window
- **WHEN** no recording_screenshots row exists within the time window for a given moment
- **THEN** that moment returns no image without raising an error; other moments/indices are unaffected

#### Scenario: Multiple screenshots in time window returns nearest one
- **WHEN** multiple screenshots exist within the time window for a given moment
- **THEN** only the single nearest screenshot by timestamp is returned (LIMIT 1)

#### Scenario: Query does not filter by source_trigger
- **WHEN** analyze_image constructs the SQL query for recording_screenshots
- **THEN** the WHERE clause contains only recording_id, moment, and timestamp range; source_trigger and capture_id do not appear in WHERE

### Requirement: All action types use the same time-window query
The system SHALL NOT branch query logic by action_type. Whether the action is click, dblclick, submit, navigate, or keydown[Enter], the same time-window query applies. This naturally covers semantic actions because their DOM timestamps are within hundreds of milliseconds of the physical input that triggered them.

#### Scenario: dblclick action finds screenshots
- **WHEN** analyze_image queries for a dblclick action
- **THEN** the time window covers the physical click screenshots and returns the nearest before/after pair

#### Scenario: submit action finds screenshots
- **WHEN** analyze_image queries for a submit action
- **THEN** the time window covers the triggering Enter/click screenshots and returns results

#### Scenario: navigate action finds screenshots
- **WHEN** analyze_image queries for a navigate action
- **THEN** the time window covers nearby screenshots and returns results if any exist

### Requirement: Persister reads screenshots queue and inserts in batches
The DuckDBRecordingPersister.save_to_duckdb() SHALL, after processing the actions queue, check for a screenshots queue file. If present, it SHALL use iter_screenshots_queue() to parse records and batch_insert_screenshots() to insert into recording_screenshots, filtering out skipped records (data=None). The Persister SHALL NOT perform pair matching or action-screenshot association.

#### Scenario: Screenshots queue exists and is valid
- **WHEN** save_to_duckdb processes a recording with both actions and screenshots queue files
- **THEN** actions are inserted into the actions table as before, and non-skipped screenshots are batch-inserted into recording_screenshots

#### Scenario: Screenshots queue is missing
- **WHEN** save_to_duckdb processes a recording with only an actions queue file
- **THEN** actions are inserted normally and no error occurs regarding the missing screenshots queue

#### Scenario: Skipped records are filtered during insert
- **WHEN** the screenshots queue contains records with skipped_reason set (data=None)
- **THEN** those records are not inserted into recording_screenshots; only records with actual screenshot data are inserted

### Requirement: Both queue files deleted on success, both preserved on failure
When save_to_duckdb succeeds, both the actions queue file and screenshots queue file SHALL be deleted. When it fails (DB exception), both files SHALL be preserved for Recovery to handle the actions queue and for startup scan to clean up the orphan screenshots queue.

#### Scenario: Successful save deletes both queues
- **WHEN** save_to_duckdb completes without error
- **THEN** both *_actions.jsonl and *_screenshots.jsonl are deleted

#### Scenario: Failed save preserves both queues
- **WHEN** save_to_duckdb throws an exception
- **THEN** both queue files remain on disk for Recovery and startup scan

### Requirement: save_to_duckdb wraps actions and screenshots in one transaction
The DuckDBRecordingPersister.save_to_duckdb() SHALL wrap the actions INSERT and the recording_screenshots INSERT within a single DuckDB transaction (BEGIN ... COMMIT). Any database-layer exception raised during either phase SHALL trigger ROLLBACK, leaving neither table with partial rows and preserving both queue files for recovery. "Success" is defined as: actions fully ingested AND screenshots queue parsed + inserted without uncaught database exceptions (row-level graceful skips inside iter_screenshots_queue DO NOT count as failures).

#### Scenario: Both phases succeed
- **WHEN** actions INSERT and recording_screenshots INSERT both complete without database exceptions
- **THEN** the transaction commits, both tables contain the new rows, and both queue files are deleted

#### Scenario: Screenshots INSERT fails rolls back actions
- **WHEN** a database exception occurs during recording_screenshots batch insert after actions have been inserted within the same transaction
- **THEN** ROLLBACK is issued, neither table contains rows from this recording, and both queue files are preserved for Recovery to re-ingest actions

#### Scenario: Actions INSERT fails preserves screenshots queue
- **WHEN** a database exception occurs during actions INSERT before screenshots processing begins
- **THEN** ROLLBACK is issued and both queue files remain on disk; the orphan screenshots queue will be cleaned up by the next startup scan

#### Scenario: Row-level skip does not count as transaction failure
- **WHEN** iter_screenshots_queue emits warnings for malformed rows but no database exception is raised
- **THEN** the transaction commits normally and both queue files are deleted

### Requirement: Orphan screenshots queue cleaned on startup
The RecordingRecovery startup scan SHALL check the queue directory on every application start (not only when WAL is abnormal). When an orphan *_screenshots.jsonl file is found (corresponding actions queue already ingested or missing), it SHALL be deleted with a log.warning.

#### Scenario: Orphan screenshots queue found on startup
- **WHEN** startup scan finds *_screenshots.jsonl without a corresponding *_actions.jsonl or the actions are already in DB
- **THEN** the orphan screenshots queue file is deleted and a warning is logged

#### Scenario: Both queues found on startup
- **WHEN** startup scan finds both *_actions.jsonl and *_screenshots.jsonl
- **THEN** actions are recovered as normal, and the screenshots queue is deleted with a warning (screenshots are not replayed)

### Requirement: recording_screenshots registered in metadata
The DuckDBManager._VALID_TABLES and _VALID_COLUMNS SHALL include recording_screenshots. The recording_data_tools._COMMON_TABLES SHALL include recording_screenshots so that describe_data and query_data can discover the table.

#### Scenario: DuckDBManager recognizes recording_screenshots
- **WHEN** DuckDBManager validates table/column access for recording_screenshots
- **THEN** the table and its columns are found in _VALID_TABLES/_VALID_COLUMNS

#### Scenario: analyze_image discovers recording_screenshots via _COMMON_TABLES
- **WHEN** describe_data lists available tables
- **THEN** recording_screenshots appears in the table list

### Requirement: ScreenshotRow dataclass and queue parsing
The screenshot_queue_parser module SHALL define a ScreenshotRow dataclass and provide iter_screenshots_queue(path) to parse JSONL line-by-line with base64 decoding, and batch_insert_screenshots(repository, rows) to filter skipped records and batch-insert into recording_screenshots via repository.insert_screenshot_batch().

#### Scenario: iter_screenshots_queue parses valid JSONL
- **WHEN** a screenshots queue file contains valid JSONL records
- **THEN** each record is yielded as a ScreenshotRow with data_b64 decoded to bytes

#### Scenario: Skipped records yield data=None
- **WHEN** a JSONL record has skipped_reason set
- **THEN** the yielded ScreenshotRow has data=None and skipped_reason populated

### Requirement: iter_screenshots_queue tolerates malformed rows
The iter_screenshots_queue iterator SHALL NOT fail-fast on single-row corruption. When a JSONL line fails JSON parsing (JSONDecodeError), is missing required fields (recording_id / moment / captured_at), or has an invalid base64 payload, the iterator SHALL emit `log.warning("skip malformed screenshot row at line N: <reason>")` and continue to the next line. Screenshots are best-effort data; single-row corruption MUST NOT block downstream insertion for the rest of the recording or trigger save_to_duckdb transaction failure.

#### Scenario: Malformed JSON line skipped gracefully
- **WHEN** a line in the screenshots queue file is not valid JSON
- **THEN** a warning is logged with the line number and reason, and the iterator continues yielding subsequent valid rows

#### Scenario: Missing required field skipped gracefully
- **WHEN** a JSONL record is missing recording_id, moment, or captured_at
- **THEN** the row is skipped with a warning and the iterator continues

#### Scenario: Invalid base64 payload skipped gracefully
- **WHEN** data_b64 cannot be base64-decoded
- **THEN** the row is skipped with a warning and the iterator continues

#### Scenario: Row-level skip does not trigger transaction rollback
- **WHEN** iter_screenshots_queue skips one or more malformed rows during save_to_duckdb
- **THEN** the surrounding DuckDB transaction continues and commits normally with the remaining valid rows

### Requirement: Repository provides insert_screenshot_batch method
The RecordingRepository SHALL provide an insert_screenshot_batch(batch) method that inserts a list of ScreenshotRow objects into recording_screenshots. Timestamp conversion SHALL use from_timestamp_utc_naive() for consistent UTC naive datetime handling, matching the actions table convention.

#### Scenario: Batch insert with timestamp conversion
- **WHEN** insert_screenshot_batch receives ScreenshotRow objects with epoch float timestamps
- **THEN** timestamps are converted to naive UTC datetime via from_timestamp_utc_naive() before binding to DuckDB TIMESTAMP columns

### Requirement: Queue paths unified via queue_paths helper
A shared queue_paths module SHALL provide get_recording_queue_dir(), get_recording_actions_queue_path(recording_id), and get_recording_screenshots_queue_path(recording_id). BrowserRecorder and RecordingRecovery SHALL both use this helper, eliminating hardcoded path construction.

#### Scenario: BrowserRecorder and RecordingRecovery use same queue dir
- **WHEN** both BrowserRecorder and RecordingRecovery call get_recording_queue_dir()
- **THEN** they resolve to the same directory path regardless of EXEMPLAR_DATA_DIR setting

#### Scenario: Screenshots queue path derived from recording_id
- **WHEN** get_recording_screenshots_queue_path("rec_001") is called
- **THEN** it returns <queue_dir>/rec_001_screenshots.jsonl
