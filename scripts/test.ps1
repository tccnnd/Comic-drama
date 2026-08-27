# Comic Drama Workflow — 本地测试运行器（T0.2 基线）
# 用法:
#   .\scripts\test.ps1                 # 跑全量测试
#   .\scripts\test.ps1 -Cov            # 带覆盖率
#   .\scripts\test.ps1 -Verbose        # 详细输出
#   .\scripts\test.ps1 -Filter "asset" # 只跑匹配用例
param(
    [switch]$Cov,
    [switch]$Verbose,
    [string]$Filter = ''
)
# 注意：禁用自动变量 $args/$Host，改用显式 $pytestArgs
$pytestArgs = @('tests', '-p', 'no:cacheprovider', "--basetemp=$env:TEMP\cd_pytest")
if ($Cov) {
    $pytestArgs += @('--cov=backend', '--cov=scripts', '--cov=video_providers.py',
                     '--cov-report=term-missing', '--cov-report=xml:coverage.xml')
}
if ($Verbose) { $pytestArgs += '-v' }
if ($Filter) { $pytestArgs += '-k', $Filter }
& .\.venv\Scripts\python.exe -m pytest @pytestArgs
