# Tasks: Parallel Tool Execution

## Phase 1 - Contract And Tests

- [X] T001 Add concurrency and ordering regression tests in `tests/integration/test_agent_loop_parallel_tools.py`
- [X] T002 Add explicit safe/serial tool-definition flag coverage

## Phase 2 - Core Implementation

- [X] T003 Add `ToolDefinition.is_concurrency_safe` with a conservative default
- [X] T004 Refactor result governance from persistence so governance can run in workers
- [X] T005 Partition ordinary batches and execute safe partitions with at most four workers
- [X] T006 Preserve caller-thread ordered persistence and existing serial cascade semantics

## Phase 3 - Tool Classification

- [X] T007 Mark reviewed built-in read tools concurrency-safe
- [X] T008 Mark `search_tools` safe while keeping mutable discovery and methodology tools serial
- [X] T009 Mark injected `load_reference` concurrency-safe

## Phase 4 - Documentation And Validation

- [X] T010 Update architecture, constraints, and backend AI entry mirrors
- [X] T011 Run focused and regression test suites
- [X] T012 Archive the completed local TODO
