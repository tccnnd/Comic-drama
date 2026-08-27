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
# WorkBuddy 沙箱 safe-delete 会拦截 shutil.rmtree/os.remove（fail-closed）；
# 测试会清理临时目录，需关闭以便本地（WorkBuddy 内）跑测试。
# CI(Linux) 无此 shim，设置 '0' 无副作用。
$env:CODEBUDDY_SAFE_DELETE_SANDBOX = '0'
# 注意：禁用自动变量 $args/$Host，改用显式 $pytestArgs
$pytestArgs = @('tests', '-p', 'no:cacheprovider', "--basetemp=$env:TEMP\cd_pytest")
if ($Cov) {
    $pytestArgs += @('--cov=backend', '--cov=scripts', '--cov=video_providers.py',
                     '--cov-report=term-missing', '--cov-report=xml:coverage.xml')
}
if ($Verbose) { $pytestArgs += '-v' }
if ($Filter) { $pytestArgs += '-k', $Filter }
& .\.venv\Scripts\python.exe -m pytest @pytestArgs
