Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "F:\videos\lives\apps\recorder"
WshShell.Run "C:\Users\franc\.local\bin\uv.EXE run src/watchdog.py", 0, False
