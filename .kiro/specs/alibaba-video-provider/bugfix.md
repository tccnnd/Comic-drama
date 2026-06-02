# Bugfix Requirements Document

## Introduction

The video provider adapter system in `scripts/video_provider_adapters.py` cannot correctly call the Alibaba Bailian (Happy Horse) image-to-video API through the memefast.top proxy. When `XL_ROUTE=unified` is configured with the Happy Horse model (`happyhorse-1.0-i2v`), the `_render_unified` function sends a flat request body format (`{"model": ..., "prompt": ..., "image": ..., "duration": ...}`) that does not match the Alibaba Bailian API's required nested format (`{"model": ..., "input": {"prompt": ..., "media": [...]}, "parameters": {...}}`). This causes the API to reject the request or return unexpected results, blocking video generation during project builds.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `XL_ROUTE=unified` and `XL_MODEL=happyhorse-1.0-i2v` and the system submits a video generation request THEN the system sends a flat body format `{"model": ..., "prompt": ..., "image": ..., "duration": ..., "aspect_ratio": ..., "resolution": ...}` which the Alibaba Bailian API does not recognize, causing the request to be rejected or return an error

1.2 WHEN `XL_ROUTE=unified` and the model name contains "happyhorse" or the submit path contains "alibailian" THEN the `_detect_route` function does not detect the Alibaba route and falls through to the "unified" handler which uses an incompatible body format

1.3 WHEN the Alibaba Bailian API returns a submit response with task_id nested under `output.task_id` (e.g., `{"output": {"task_id": "...", "task_status": "PENDING"}}`) THEN the unified handler's `_extract_task_id` may fail to locate the task_id because it does not check the `output` key at the top level of its search hierarchy

1.4 WHEN the Alibaba Bailian poll response returns the video URL nested under `output.video_url` (e.g., `{"output": {"task_status": "SUCCEEDED", "video_url": "..."}}`) THEN the system may fail to extract the video URL if the nested `output` traversal does not match the expected response structure

### Expected Behavior (Correct)

2.1 WHEN `XL_ROUTE=alibaba` (or auto-detected via model/path) and `XL_MODEL=happyhorse-1.0-i2v` and the system submits a video generation request THEN the system SHALL send the request body in Alibaba Bailian format: `{"model": "happyhorse-1.0-i2v", "input": {"prompt": "...", "media": [{"type": "first_frame", "url": "..."}]}, "parameters": {"resolution": "720P", "duration": 5, "watermark": false}}`

2.2 WHEN the model name contains "happyhorse" or "bailian" or the submit path contains "alibailian" THEN the `_detect_route` function SHALL detect and return the "alibaba" route so the correct handler is invoked

2.3 WHEN the Alibaba Bailian API returns a submit response with `{"output": {"task_id": "...", "task_status": "PENDING"}}` THEN the system SHALL correctly extract the `task_id` from the nested `output.task_id` field

2.4 WHEN the Alibaba Bailian poll endpoint returns `{"output": {"task_id": "...", "task_status": "SUCCEEDED", "video_url": "..."}}` THEN the system SHALL correctly extract the video URL from `output.video_url` and download the video

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `XL_ROUTE=unified` and the model is not a Happy Horse / Alibaba model THEN the system SHALL CONTINUE TO send the flat unified body format and process responses as before

3.2 WHEN `XL_ROUTE=kling` THEN the system SHALL CONTINUE TO use the Kling handler with its existing body format and response parsing

3.3 WHEN `XL_ROUTE=volc` THEN the system SHALL CONTINUE TO use the Volc/Seedance handler with its existing body format and response parsing

3.4 WHEN `XL_ROUTE=openai_official` THEN the system SHALL CONTINUE TO use the OpenAI Official handler with its multipart upload format and response parsing

3.5 WHEN a non-Alibaba provider returns task_id or video_url in existing response structures (flat or nested under `data`/`result`/`response`) THEN the `_extract_task_id` and `_extract_video_url` functions SHALL CONTINUE TO correctly extract those values
