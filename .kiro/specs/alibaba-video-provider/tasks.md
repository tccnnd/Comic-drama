# Implementation Plan

## Overview

Bugfix implementation for the Alibaba Bailian (Happy Horse) video provider adapter. The fix adds Alibaba route detection, a dedicated render handler with the correct nested body format, and ensures response parsing handles Alibaba's `output`-wrapped structure. Follows the exploratory bugfix workflow: explore the bug with tests, preserve existing behavior, implement the fix, then validate.

## Tasks

- [ ] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Alibaba Bailian Request Format
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to concrete failing cases: model names containing "happyhorse" or "bailian", and Alibaba-style nested responses
  - Test that `_detect_route` with model `"happyhorse-1.0-i2v"` returns `"alibaba"` (from Bug Condition: `isBugCondition` where model CONTAINS "happyhorse" OR "bailian")
  - Test that `_detect_route` with submit path containing `"alibailian"` returns `"alibaba"`
  - Test that `_extract_task_id({"output": {"task_id": "abc123", "task_status": "PENDING"}})` returns `"abc123"` (currently returns empty string)
  - Test that rendering with a Happy Horse model produces nested body format `{"model": ..., "input": {...}, "parameters": {...}}` instead of flat format
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found:
    - `_detect_route("XL", spec, "happyhorse-1.0-i2v")` returns "unified" instead of "alibaba"
    - `_extract_task_id({"output": {"task_id": "test-123"}})` returns "" instead of "test-123"
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [ ] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-Alibaba Provider Behavior
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: `_detect_route` with model `"kling-v1"` returns `"kling"` on unfixed code
  - Observe: `_detect_route` with model `"seedance-1.0"` returns `"volc"` on unfixed code
  - Observe: `_detect_route` with model `"sora-2"` returns `"openai_official"` on unfixed code
  - Observe: `_detect_route` with model `"generic-model"` returns `"unified"` on unfixed code
  - Observe: `_extract_task_id({"task_id": "flat-123"})` returns `"flat-123"` on unfixed code
  - Observe: `_extract_task_id({"data": {"task_id": "nested-456"}})` returns `"nested-456"` on unfixed code
  - Observe: `_extract_video_url` correctly extracts URLs from existing response structures on unfixed code
  - Write property-based test: for all model names NOT containing "happyhorse", "bailian", or "alibailian", `_detect_route` returns the same route as the original code (from Preservation Requirements in design)
  - Write property-based test: for all response structures with `task_id` at existing nesting levels (flat, under `data`, under `result`, under `response`), `_extract_task_id` returns the same result as original code
  - Write property-based test: for all non-Alibaba response structures, `_extract_video_url` returns the same result as original code
  - Verify tests pass on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 3. Fix for Alibaba Bailian video provider adapter

  - [ ] 3.1 Add Alibaba route detection to `_detect_route`
    - Add pattern check: `if "happyhorse" in name or "bailian" in name or "alibailian" in name: return "alibaba"`
    - Insert before the final `return "unified"` fallback
    - Ensure the combined `name` string includes spec.id + model for matching
    - _Bug_Condition: isBugCondition(input) where model CONTAINS "happyhorse" OR "bailian" OR submit_path CONTAINS "alibailian"_
    - _Expected_Behavior: _detect_route returns "alibaba" for Alibaba models_
    - _Preservation: Non-Alibaba models (kling, volc, sora, generic) must still route correctly_
    - _Requirements: 1.2, 2.2, 3.1, 3.2, 3.3, 3.4_

  - [ ] 3.2 Create dedicated `_render_alibaba` handler
    - Implement `_render_alibaba` function that constructs nested body format:
      - `{"model": model, "input": {"prompt": prompt_text, "media": [{"type": "first_frame", "url": first_frame_url}]}, "parameters": {"resolution": resolution, "duration": int(round(duration)), "watermark": False}}`
    - Use `_first_frame_url` to obtain the image URL
    - Configure default `SUBMIT_PATH` for Alibaba's async task endpoint
    - Configure default `POLL_PATH` for Alibaba's task query endpoint
    - _Bug_Condition: isBugCondition(input) where Alibaba model is used with unified handler_
    - _Expected_Behavior: System sends nested Alibaba Bailian format per design spec_
    - _Preservation: _render_unified remains unchanged for non-Alibaba models_
    - _Requirements: 1.1, 2.1_

  - [ ] 3.3 Add `output` key to `_extract_task_id` search hierarchy
    - Add check for `output` key in `_extract_task_id` function
    - Position after existing `response` check (or before for priority)
    - Ensure `{"output": {"task_id": "..."}}` structure is correctly parsed
    - _Bug_Condition: isBugCondition(input) where Alibaba response wraps task_id under output_
    - _Expected_Behavior: _extract_task_id returns task_id from output.task_id_
    - _Preservation: Existing extraction from flat, data, result, response structures unchanged_
    - _Requirements: 1.3, 2.3, 3.5_

  - [ ] 3.4 Add Alibaba route dispatch in `render_remote_video_provider`
    - Add `if route == "alibaba"` branch in route dispatch section
    - Call `_render_alibaba` when route is "alibaba"
    - _Bug_Condition: isBugCondition(input) where route should be "alibaba" but dispatches to unified_
    - _Expected_Behavior: Alibaba route dispatches to _render_alibaba handler_
    - _Preservation: All other route dispatches (kling, volc, openai_official, unified) unchanged_
    - _Requirements: 2.1, 2.2_

  - [ ] 3.5 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Alibaba Bailian Request Format
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [ ] 3.6 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-Alibaba Provider Behavior
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [ ] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Task Dependency Graph

```json
{
  "waves": [
    ["1"],
    ["2"],
    ["3.1", "3.2", "3.3", "3.4"],
    ["3.5", "3.6"],
    ["4"]
  ]
}
```

## Notes

- Tests in tasks 1 and 2 MUST be written and run BEFORE implementing the fix in task 3
- Task 1 exploration test is expected to FAIL on unfixed code (this confirms the bug exists)
- Task 2 preservation tests are expected to PASS on unfixed code (this captures baseline behavior)
- After fix implementation (3.1-3.4), re-running the same tests validates correctness
- The target file for all code changes is `scripts/video_provider_adapters.py`
- Property-based testing is recommended for stronger preservation guarantees across the input domain
