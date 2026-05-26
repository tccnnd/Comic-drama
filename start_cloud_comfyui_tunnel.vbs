Set shell = CreateObject("WScript.Shell")
Set env = shell.Environment("Process")

password = env("CLOUD_COMFYUI_SSH_PASSWORD")
If Len(password) = 0 Then
  WScript.Echo "Missing CLOUD_COMFYUI_SSH_PASSWORD"
  WScript.Quit 1
End If

root = "E:\APP\Comic drama"
env("CLOUD_COMFYUI_SSH_PASSWORD") = password
cmd = """" & root & "\.venv\Scripts\python.exe"" """ & root & "\scripts\cloud_comfyui_tunnel.py"""

shell.Run cmd, 0, False
