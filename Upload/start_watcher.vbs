Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
WshShell.CurrentDirectory = FSO.GetParentFolderName(WScript.ScriptFullName)

' Restart loop — if Python crashes, relaunch after 15 seconds.
' "True" means wscript waits for python.exe to exit before looping.
Do
    WshShell.Run """C:\Program Files\Python311\python.exe"" render_watcher.py", 0, True
    WScript.Sleep 15000
Loop
