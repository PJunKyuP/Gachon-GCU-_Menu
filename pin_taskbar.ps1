param(
    [string]$ExePath = "$PSScriptRoot\dist\GachonMenu.exe"
)

if (-not (Test-Path $ExePath)) {
    Write-Host "Executable not found: $ExePath"
    Write-Host "Run build_exe.bat first."
    exit 1
}

$shell = New-Object -ComObject Shell.Application
$folder = $shell.Namespace((Split-Path $ExePath))
$item = $folder.ParseName((Split-Path $ExePath -Leaf))

if (-not $item) {
    Write-Host "Failed to read file shell info."
    exit 1
}

try {
    $item.InvokeVerb("taskbarunpin")
    Start-Sleep -Milliseconds 400
    $item.InvokeVerb("taskbarpin")
    Start-Sleep -Milliseconds 400
    Write-Host "Taskbar pin refresh command sent."
    Write-Host "If the icon does not update immediately, unpin and pin once manually."
    exit 0
}
catch {
    Write-Host "Automatic taskbar refresh failed."
    Write-Host "Please pin dist\GachonMenu.exe manually from Explorer."
    exit 2
}
