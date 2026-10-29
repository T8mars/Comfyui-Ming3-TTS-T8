param([string]$ComfyPath)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$mingBundleRoot = $PSScriptRoot
if (-not $ComfyPath) { $ComfyPath = Read-Host '请输入 ComfyUI 文件夹路径（包含 main.py）' }
$mingComfyRoot = (Resolve-Path -LiteralPath $ComfyPath).Path
if (-not (Test-Path -LiteralPath (Join-Path $mingComfyRoot 'main.py'))) {
    throw '该目录没有 main.py，请选择 ComfyUI 本体文件夹。'
}
$mingNodeRoot = Join-Path $mingComfyRoot 'custom_nodes\ComfyUI-Ming3-TTS-T8'
if (Test-Path -LiteralPath $mingNodeRoot) { throw '节点目录已存在。为保留原有设置，本安装器不会覆盖，请先在管理器中处理旧版本。' }
New-Item -ItemType Directory -Path $mingNodeRoot | Out-Null
foreach ($mingName in @('__init__.py','nodes.py','requirements.txt','README.md','THIRD_PARTY_NOTICES.md','ming_t8','web','examples','native')) {
    Copy-Item -LiteralPath (Join-Path $mingBundleRoot $mingName) -Destination $mingNodeRoot -Recurse
}
foreach ($mingComponent in @('cuda','confucius\.runtime','ffmpeg')) {
    $mingSource = Join-Path $mingBundleRoot ('components\' + $mingComponent)
    $mingTarget = Join-Path $mingNodeRoot ('components\' + $mingComponent)
    New-Item -ItemType Directory -Path (Split-Path -Parent $mingTarget) -Force | Out-Null
    Copy-Item -LiteralPath $mingSource -Destination $mingTarget -Recurse
}
$mingSettings = @{
    data_root = (Join-Path $mingBundleRoot 'data')
    model_path = (Join-Path $mingBundleRoot 'data\models\Ming-Comfy-INT8\checkpoints\ming_tts_tiny_int8_convrot.safetensors')
    assets_path = (Join-Path $mingBundleRoot 'data\models\Ming-3.0-tts-tiny')
    asr_root = (Join-Path $mingBundleRoot 'components\confucius')
    native_kernels = 'auto'
    attention_backend = 'sdpa'
    cuda_graphs = $true
}
[System.IO.File]::WriteAllText((Join-Path $mingNodeRoot 'settings.local.json'), ($mingSettings | ConvertTo-Json), [System.Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $mingBundleRoot 'licenses') -Destination $mingNodeRoot -Recurse
$mingInputFolder = Join-Path $mingComfyRoot 'input'
New-Item -ItemType Directory -Path $mingInputFolder -Force | Out-Null
Get-ChildItem -LiteralPath (Join-Path $mingBundleRoot 'examples\audio') -Filter '*.wav' | ForEach-Object {
    $mingReferenceTarget = Join-Path $mingInputFolder $_.Name
    if (-not (Test-Path -LiteralPath $mingReferenceTarget)) { Copy-Item -LiteralPath $_.FullName -Destination $mingReferenceTarget }
}
Write-Host '节点已复制；模型使用整合包中的同一份文件。'
Write-Host '请用 ComfyUI 自己的 Python 安装节点 requirements.txt，然后重启 ComfyUI。不要更换现有 Torch。'
Write-Host ('节点目录：' + $mingNodeRoot)
