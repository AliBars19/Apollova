$batFile = "C:\Users\aliba\Downloads\Apollova\Apollova\Apollova-Installer\build_setup.bat"
$logFile = "C:\Users\aliba\Downloads\Apollova\Apollova\Apollova-Installer\build_output.log"
$workDir = "C:\Users\aliba\Downloads\Apollova\Apollova\Apollova-Installer"

Set-Location $workDir
$output = & cmd.exe /c "`"$batFile`"" 2>&1
$output | Out-File -FilePath $logFile -Encoding utf8
$output | Select-Object -Last 50
