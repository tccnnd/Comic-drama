# Alibaba Video Provider Bugfix Design

## Overview

The video provider adapter system in `scripts/video_provider_adapters.py` fails to correctly call the Alibaba Bailian (Happy Horse) image-to-video API through the memefast.top proxy. Three interrelated defects prevent successful video generation: (1) `_detect_route` does not recognize Alibaba/Happy Horse models, causing fallback to the incompatible "unified" handler; (2) no dedicated `_render_alibaba` handler exists to construct the nested request body format required by the Alibaba Bailian API; (3) `_extract_task_id` does not check the `output` key early enough in its search hierarchy to locate `output.task_id` in Alibaba responses. The fix adds Alibaba route detection, a dedicated render handler with the correct nested body format, and ensures response parsing handles Alibaba's `output`-wrapped structure.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug — when the system attempts to generate video using an Alibaba Bailian model (e.g., `happyhorse-1.0-i2v`) and the request is routed through the unified handler with an incompatible flat body format
- **Property (P)**: The desired behavior — the system sends the correct nested Alibaba Bailian body format and correctly parses the nested `output.task_id` and `output.video_url` response fields
- **Preservation**: Existing behavior for non-Alibaba providers (unified, kling, volc, openai_official) must remain unchanged
- **`_detect_route`**: The function in `scripts/video_provider_adapters.py` that determines which render handler to invoke based on model name, spec ID, and explicit route configuration
- **`_render_unified`**: The fallback render handler that sends a flat body format incompatible with Alibaba Bailian
- **`_extract_task_id`**: The recursive function that searches response payloads for task identifiers across multiple key names and nesting levels
- **`_extract_video_url`**: The recursive function that searches response payloads for video download URLs
- **memefast.top proxy**: The API proxy endpoint through which Alibaba Bailian requests are routed

## Bug Details

### Bug Condition

The bug manifests when a user configures the system to use an Alibaba Bailian model (e.g., `happyhorse-1.0-i2v`) for video generation. The `_detect_route` function does not recognize "happyhorse" or "bailian" or "alibailian" patterns, so it falls through to the "unified" route. The `_render_unified` handler then sends a flat body format (`{"model": ..., "prompt": ..., "image": ..., "duration": ...}`) that the Alibaba Bailian API rejects because it expects a nested format (`{"model": ..., "input": {...}, "parameters": {...}}`).

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type VideoRenderRequest + VideoProviderSpec + environment config
  OUTPUT: boolean
  
  LET model = configured model name (e.g., "happyhorse-1.0-i2v")
  LET route = _detect_route(prefix, spec, model)
  LET submit_path = configured SUBMIT_PATH
  
  RETURN (model CONTAINS "happyhorse" OR model CONTAINS "bailian"
          OR submit_path CONTAINS "alibailian"
          OR spec.id CONTAINS "alibaba" OR spec.id CONTAINS "bailian")
         AND route != "alibaba"
END FUNCTION
```

### Examples

- **Example 1**: `XL_MODEL=happyhorse-1.0-i2v`, `XL_ROUTE=unified` → System sends `{"model": "happyhorse-1.0-i2v", "prompt": "...", "image": "...", "duration": 5}` → API rejects with format error. **Expected**: System sends `{"model": "happyhorse-1.0-i2v", "input": {"prompt": "...", "media": [{"type": "first_frame", "url": "..."}]}, "parameters": {"resolution": "720P", "duration": 5}}`
- **Example 2**: `XL_MODEL=happyhorse-1.0-i2v`, no explicit `XL_ROUTE` → `_detect_route` returns "unified" because it has no pattern match for "happyhorse" → Same flat body failure. **Expected**: `_detect_route` returns "alibaba"
- **Example 3**: Alibaba submit response `{"output": {"task_id": "abc123", "task_status": "PENDING"}}` → `_extract_task_id` checks `task_id` at top level (not found), then `data`, `result`, `response` keys (not found), never checks `output` → Returns empty string. **Expected**: Returns "abc123"
- **Example 4**: Alibaba poll response `{"output": {"task_status": "SUCCEEDED", "video_url": "https://..."}}` → `_extract_video_url` eventually finds it via the `output` key (which is checked last in the current code) → This case may work but is fragile. **Expected**: Reliable extraction from `output.video_url`

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- The `_render_unified` handler must continue to send the flat body format for non-Alibaba models (e.g., generic proxy models)
- The `_render_kling` handler must continue to use its `model_name`-based body format and Kling-specific paths
- The `_render_volc` handler must continue to use its `content`-array body format and Volc-specific paths
- The `_render_openai_official` handler must continue to use multipart upload format
- `_extract_task_id` must continue to find task IDs in existing response structures (`data`, `result`, `response` nesting)
- `_extract_video_url` must continue to find video URLs in existing response structures

**Scope:**
All inputs that do NOT involve Alibaba Bailian models (no "happyhorse", "bailian", or "alibailian" in model name or submit path) should be completely unaffected by this fix. This includes:
- Kling model requests
- Volc/Seedance model requests
- OpenAI/Sora model requests
- Generic unified proxy requests with non-Alibaba models

## Hypothesized Root Cause

Based on the bug description, the most likely issues are:

1. **Missing Route Detection Pattern**: The `_detect_route` function checks for "sora", "seedance", "doubao", and "kling" patterns but has no check for "happyhorse", "bailian", or "alibailian". This causes Alibaba models to fall through to the default "unified" route.

2. **No Dedicated Alibaba Render Handler**: There is no `_render_alibaba` function. Even if route detection were fixed, there is no handler to construct the nested `{"model": ..., "input": {...}, "parameters": {...}}` body format required by the Alibaba Bailian API.

3. **`_extract_task_id` Search Order**: The function checks top-level keys first, then recurses into `data`, `result`, and `response` — but does NOT recurse into `output`. Alibaba's response wraps `task_id` under `output.task_id`, which is never reached by the current search logic.

4. **`_extract_video_url` Fragility**: While `_extract_video_url` does check the `output` key, it does so last in the search order. This works but is fragile and inconsistent with `_extract_task_id`'s behavior, creating a discrepancy where task submission fails but polling might accidentally succeed.

## Correctness Properties

Property 1: Bug Condition - Alibaba Bailian Request Format

_For any_ video render request where the model name contains "happyhorse" or "bailian", or the submit path contains "alibailian", the fixed system SHALL send the request body in Alibaba Bailian nested format with `input.prompt`, `input.media[]`, and `parameters` fields, and SHALL correctly extract `task_id` from the `output.task_id` response field.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - Non-Alibaba Provider Behavior

_For any_ video render request where the model name does NOT contain "happyhorse" or "bailian" and the submit path does NOT contain "alibailian", the fixed system SHALL produce exactly the same request body format, use the same route handler, and parse responses identically to the original code, preserving all existing provider functionality.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `scripts/video_provider_adapters.py`

**Function**: `_detect_route`

**Specific Changes**:
1. **Add Alibaba pattern detection**: Add a check for "happyhorse", "bailian", or "alibailian" in the combined `name` string (spec.id + model). Return `"alibaba"` when matched. Insert this check before the final `return "unified"` fallback.
   - Pattern: `if "happyhorse" in name or "bailian" in name or "alibailian" in name: return "alibaba"`

**Function**: NEW `_render_alibaba`

2. **Create dedicated Alibaba render handler**: Implement `_render_alibaba` that constructs the nested body format:
   ```python
   body = {
       "model": model,
       "input": {
           "prompt": prompt_text,
           "media": [{"type": "first_frame", "url": first_frame_url}],
       },
       "parameters": {
           "resolution": resolution,  # e.g., "720P"
           "duration": int(round(duration)),
           "watermark": False,
       },
   }
   ```
   - Use `_first_frame_url` to obtain the image URL
   - Use configurable `SUBMIT_PATH` defaulting to Alibaba's async task endpoint
   - Use configurable `POLL_PATH` defaulting to Alibaba's task query endpoint

**Function**: `_extract_task_id`

3. **Add `output` key to search hierarchy**: Add a check for the `output` key in `_extract_task_id`, positioned after `response` (or before, for priority). This ensures Alibaba's `{"output": {"task_id": "..."}}` structure is correctly parsed.
   ```python
   output = payload.get("output")
   if isinstance(output, dict):
       return _extract_task_id(output)
   ```

**Function**: `render_remote_video_provider` (route dispatch)

4. **Add Alibaba route dispatch**: Add an `if route == "alibaba"` branch in the route dispatch section of `render_remote_video_provider` that calls `_render_alibaba`.

5. **Default paths for Alibaba**: Configure sensible defaults for Alibaba Bailian API paths:
   - Submit: `/api/v1/services/aigc/video-generation/generation` (or configurable via `SUBMIT_PATH`)
   - Poll: `/api/v1/tasks/{task_id}` (or configurable via `POLL_PATH`)

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write unit tests that invoke `_detect_route` with Alibaba model names and verify the returned route. Write tests that invoke `_extract_task_id` with Alibaba-style nested responses. Run these tests on the UNFIXED code to observe failures.

**Test Cases**:
1. **Route Detection Test**: Call `_detect_route` with model `"happyhorse-1.0-i2v"` — expect "alibaba" but will get "unified" on unfixed code (will fail on unfixed code)
2. **Task ID Extraction Test**: Call `_extract_task_id({"output": {"task_id": "abc123", "task_status": "PENDING"}})` — expect "abc123" but will get "" on unfixed code (will fail on unfixed code)
3. **Body Format Test**: Invoke `_render_unified` with a Happy Horse model and inspect the generated body — expect nested format but will get flat format (will fail on unfixed code)
4. **Auto-Detection Test**: Call `_detect_route` with submit path containing "alibailian" — expect "alibaba" but will get "unified" (will fail on unfixed code)

**Expected Counterexamples**:
- `_detect_route("XL", spec, "happyhorse-1.0-i2v")` returns "unified" instead of "alibaba"
- `_extract_task_id({"output": {"task_id": "test-123"}})` returns "" instead of "test-123"
- Possible causes: missing pattern in `_detect_route`, missing `output` key in `_extract_task_id` search

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := render_remote_video_provider_fixed(input)
  ASSERT request_body_has_nested_format(result)
  ASSERT task_id_extracted_correctly(result)
  ASSERT video_url_extracted_correctly(result)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT _detect_route_original(input) = _detect_route_fixed(input)
  ASSERT _extract_task_id_original(input) = _extract_task_id_fixed(input)
  ASSERT _render_unified_original(input) = _render_unified_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (random model names, random response structures)
- It catches edge cases that manual unit tests might miss (e.g., model names that partially match patterns)
- It provides strong guarantees that behavior is unchanged for all non-Alibaba inputs

**Test Plan**: Observe behavior on UNFIXED code first for non-Alibaba models (kling, volc, unified), then write property-based tests capturing that behavior.

**Test Cases**:
1. **Route Detection Preservation**: Verify that `_detect_route` returns the same route for all non-Alibaba model names (kling-v1, seedance-1.0, sora-2, generic-model) before and after the fix
2. **Task ID Extraction Preservation**: Verify that `_extract_task_id` returns the same result for all non-Alibaba response structures (flat `task_id`, nested under `data`, nested under `result`)
3. **Video URL Extraction Preservation**: Verify that `_extract_video_url` returns the same result for all existing response structures
4. **Unified Handler Preservation**: Verify that `_render_unified` produces the same body format for non-Alibaba models

### Unit Tests

- Test `_detect_route` returns "alibaba" for "happyhorse-1.0-i2v", "bailian-video", and paths containing "alibailian"
- Test `_detect_route` still returns "kling", "volc", "openai_official", "unified" for their respective models
- Test `_extract_task_id` correctly extracts from `{"output": {"task_id": "..."}}`
- Test `_extract_task_id` still works for `{"task_id": "..."}`, `{"data": {"task_id": "..."}}`, etc.
- Test `_render_alibaba` produces the correct nested body format
- Test edge cases: model name "happyhorse" with explicit `XL_ROUTE=unified` override

### Property-Based Tests

- Generate random model names (excluding Alibaba patterns) and verify `_detect_route` returns the same result before and after fix
- Generate random response dictionaries with `task_id` at various nesting levels and verify `_extract_task_id` returns the same result
- Generate random Alibaba-style inputs (model names containing "happyhorse"/"bailian", various durations, resolutions) and verify the body format is always correctly nested
- Generate random non-Alibaba response structures and verify `_extract_video_url` behavior is unchanged

### Integration Tests

- Test full video generation flow with `XL_MODEL=happyhorse-1.0-i2v` against a mock Alibaba Bailian endpoint
- Test that switching between providers (kling → alibaba → unified) produces correct body formats for each
- Test the complete submit → poll → download cycle with Alibaba's nested response format
