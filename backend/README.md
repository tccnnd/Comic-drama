# Backend

Run the local API server:

```powershell
.\.venv\Scripts\uvicorn.exe backend.app:app --reload --host 127.0.0.1 --port 8000
```

Create a task:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/projects -ContentType 'application/json' -Body '{"title":"霸总的限时娇妻","planner":"rule","keyframe_provider":"local","voice_provider":"auto","scene_count":5}'
```
