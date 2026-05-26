$root = "E:\APP\Comic drama"
Set-Location $root
[System.Environment]::SetEnvironmentVariable("PATH", $null, "Process")
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:CLOUD_COMFYUI_SSH_PASSWORD = "replace-with-your-password"
$process = Start-Process -WindowStyle Hidden -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList "scripts\dev_server.py" -WorkingDirectory $root -PassThru
Start-Sleep -Seconds 2
$listener = netstat -ano | Select-String "127.0.0.1:8000\s+0.0.0.0:0\s+LISTENING\s+(\d+)"
if ($listener -and $listener.Matches.Count -gt 0) {
    Set-Content -Path "$root\dev_server.pid" -Value $listener.Matches[0].Groups[1].Value
} else {
    Set-Content -Path "$root\dev_server.pid" -Value $process.Id
}
