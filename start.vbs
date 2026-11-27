Option Explicit

Dim shell, files, folder, python, environment, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
folder = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(folder, ".venv\Scripts\pythonw.exe")

If Not files.FileExists(python) Then
    MsgBox "Project Python environment not found. Create .venv and install dependencies as described in README.md.", vbExclamation, "E2S"
    WScript.Quit 1
End If

shell.CurrentDirectory = folder
Set environment = shell.Environment("Process")
environment("PYTHONPATH") = files.BuildPath(folder, "src")
environment("PYTHONNOUSERSITE") = "1"
command = """" & python & """ -m e2s"
shell.Run command, 0, False
