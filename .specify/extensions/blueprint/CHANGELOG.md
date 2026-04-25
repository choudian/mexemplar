# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-04-15

### Added

- `/speckit.blueprint.generate` command with two modes: doc-only, scaffold
- `/speckit.blueprint.validate` command for scaffold validation
- `after_tasks` hook for automatic blueprint generation
- `before_implement` hook as safety net when blueprint.md is missing
- Language-agnostic scaffold validation script (validate-scaffold.sh)
- Support for spec artifacts: tasks.md, spec.md, plan.md, data-model.md, contracts/
- Tags for catalog discoverability: blueprint, pre-implementation, review
- "The Gap This Extension Fills" section in README
- "Why Not Just Review the PR After Implementation?" FAQ section in README
