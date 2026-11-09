# 使用 Windows 系统自带 OCR（Windows.Media.Ocr）识别图片中的中英文。
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File ocr-windows.ps1 -ImagePath <png路径>
param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]

$getAwaiterBaseMethod = [WindowsRuntimeSystemExtensions].GetMember('GetAwaiter') |
    Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } |
    Select-Object -First 1

Function Await($AsyncTask, $ResultType) {
    $getAwaiterBaseMethod.MakeGenericMethod($ResultType).Invoke($null, @($AsyncTask)).GetResult()
}

$path = [System.IO.Path]::GetFullPath($ImagePath)
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

# 中文优先（zh-Hans），不可用时回退系统首选语言
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$lang = [Windows.Globalization.Language]::new("zh-Hans")
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if ($null -eq $engine) {
    Write-Error "本机没有可用的 OCR 语言包"
    exit 1
}

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$lines = @()
foreach ($line in $result.Lines) {
    $lines += $line.Text
}
$stream.Dispose()
$bitmap.Dispose()
$out = [string]::Join([Environment]::NewLine, $lines)
Write-Output $out
