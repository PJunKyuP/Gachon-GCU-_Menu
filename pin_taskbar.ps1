param(
    [string]$ExePath = "$PSScriptRoot\dist\GachonMealWidget.exe"
)

if (-not (Test-Path $ExePath)) {
    Write-Host "실행파일을 찾을 수 없습니다: $ExePath"
    Write-Host "먼저 build_exe.bat 를 실행해 주세요."
    exit 1
}

$shell = New-Object -ComObject Shell.Application
$folder = $shell.Namespace((Split-Path $ExePath))
$item = $folder.ParseName((Split-Path $ExePath -Leaf))

if (-not $item) {
    Write-Host "파일 정보를 가져오지 못했습니다."
    exit 1
}

$verb = $item.Verbs() |
    Where-Object { $_.Name.Replace('&', '') -match '작업 표시줄에 고정|Pin to taskbar' } |
    Select-Object -First 1

if ($verb) {
    $verb.DoIt()
    Write-Host "작업표시줄 고정 명령을 실행했습니다."
    Write-Host "권한/정책에 따라 수동 고정이 필요할 수 있습니다."
    exit 0
}

Write-Host "자동 고정 메뉴를 찾지 못했습니다."
Write-Host "dist\GachonMealWidget.exe 를 우클릭해서 '작업 표시줄에 고정' 해주세요."
exit 2
