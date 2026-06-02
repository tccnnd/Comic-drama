# Contributing

Thanks for your interest in Comic Drama Workflow.

This project is an early-stage AI production workflow. The most useful
contributions are practical improvements to script parsing, character
consistency, timeline structure, provider integration, review tooling, and
documentation.

## How To Contribute

1. Open an issue before large changes.
2. Keep pull requests focused on one behavior or module.
3. Include a short explanation of why the change matters for the production
   workflow.
4. Add or update documentation when behavior changes.
5. Do not commit generated videos, large model files, API keys, or private
   project data.

## Development Checks

Run the checks that match the files you touched:

```powershell
python -m py_compile scripts\run_workflow.py backend\project_runtime.py
```

For frontend changes, use the bundled or local Node runtime:

```powershell
node --check frontend\app.js
```

If your change affects rendering, run a short sample workflow:

```powershell
python scripts\run_workflow.py --input inputs\sample_story.txt
```

## Issue Labels

Suggested categories:

- `script-import`
- `character-consistency`
- `timeline`
- `video-provider`
- `comfyui`
- `frontend`
- `docs`
- `bug`
- `research`

## Security And Credentials

Never include API keys, SSH credentials, cloud instance details, private
reference images, or generated user content in a pull request. Use `.env` for
local credentials and keep it out of commits.

## Model And Asset Licensing

When adding model adapters or workflow templates, document any model license,
commercial-use restriction, attribution requirement, or hosting assumption.
