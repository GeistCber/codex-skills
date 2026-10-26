param(
    [Parameter(Mandatory=$true)][ValidateSet('gh','git')][string]$Tool,
    [Parameter(Mandatory=$true)][string[]]$Arguments,
    [string]$ExpectedLogin='GeistCber'
)

$ErrorActionPreference='Stop'
if(-not (Get-Command gh -ErrorAction SilentlyContinue)){throw '未找到GitHub CLI，请先安装gh。'}
if(-not (Get-Command git -ErrorAction SilentlyContinue)){throw '未找到Git，请先安装Git。'}
if($Arguments.Count -eq 0){throw '缺少要执行的命令。'}

# 不允许通过通用助手导出凭据；正常仓库操作不需要这些命令。
if($Tool -eq 'gh' -and (($Arguments.Count -gt 1 -and $Arguments[0] -eq 'auth' -and $Arguments[1] -eq 'token') -or $Arguments -contains '--show-token')){
    throw '连接助手不提供凭据导出。'
}
if($Tool -eq 'git' -and @($Arguments | Where-Object {$_ -match '^credential($|-)'}).Count -gt 0){
    throw '连接助手不提供凭据导出。'
}

# 所有环境变量仅临时用于本次调用；成功或异常均恢复原值。
$sessionVariables=@('HTTPS_PROXY','HTTP_PROXY','GH_TOKEN','GITHUB_TOKEN','GCM_INTERACTIVE','GIT_TERMINAL_PROMPT')
$previous=@{}
foreach($key in $sessionVariables){$previous[$key]=[Environment]::GetEnvironmentVariable($key,'Process')}
$commandExit=1
try {
    if(-not $env:HTTPS_PROXY -and -not $env:HTTP_PROXY){
        $settings=Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
        if($settings -and $settings.ProxyEnable -eq 1 -and $settings.ProxyServer){
            $proxyAddress=$settings.ProxyServer
            if($proxyAddress -match '='){
                $httpsEntry=@($proxyAddress -split ';' | Where-Object {$_ -match '^https='}) | Select-Object -First 1
                $httpEntry=@($proxyAddress -split ';' | Where-Object {$_ -match '^http='}) | Select-Object -First 1
                $proxyAddress=if($httpsEntry){$httpsEntry.Substring(6)}elseif($httpEntry){$httpEntry.Substring(5)}else{''}
            }
            if($proxyAddress){
                if($proxyAddress -notmatch '^[a-z][a-z0-9+.-]*://'){$proxyAddress='http://'+$proxyAddress}
                $env:HTTPS_PROXY=$proxyAddress
                $env:HTTP_PROXY=$proxyAddress
            }
        }
    }
    $env:GCM_INTERACTIVE='Never'
    $env:GIT_TERMINAL_PROMPT='0'

    # gh的旧登录可能无效，而Git Credential Manager仍有可用凭据。
    # 所有敏感输出只接入变量，不回显、不写文件、不放入远程URL或命令参数。
    $login=@(& gh api user --jq .login 2>$null)
    $loginExit=$LASTEXITCODE
    if($loginExit -ne 0){
        $credentialLines=@('protocol=https','host=github.com',('username='+$ExpectedLogin),'','') | & git -c credential.interactive=false credential fill 2>$null
        $credentialExit=$LASTEXITCODE
        $passwordLine=$credentialLines | Where-Object {$_ -like 'password=*'} | Select-Object -First 1
        if($credentialExit -ne 0 -or -not $passwordLine){throw '未找到可用GitHub登录，请通过gh auth login完成浏览器授权后重试。'}
        $env:GH_TOKEN=$passwordLine.Substring(9)
        $credentialLines=$null
        $passwordLine=$null
        $login=@(& gh api user --jq .login 2>$null)
        $loginExit=$LASTEXITCODE
    }
    if($loginExit -ne 0){throw 'GitHub身份验证未成功，请检查登录或当前网络连接。'}
    $actualLogin=($login -join '').Trim()
    if(-not [string]::Equals($actualLogin,$ExpectedLogin,[StringComparison]::OrdinalIgnoreCase)){
        throw ('当前GitHub账号为'+$actualLogin+'，与指定账号'+$ExpectedLogin+'不一致；尚未执行目标命令。')
    }

    if($Tool -eq 'gh'){& gh @Arguments}else{& git @Arguments}
    $commandExit=$LASTEXITCODE
}
finally {
    foreach($key in $sessionVariables){
        if($null -eq $previous[$key]){Remove-Item -LiteralPath ('Env:'+$key) -ErrorAction SilentlyContinue}
        else{[Environment]::SetEnvironmentVariable($key,$previous[$key],'Process')}
    }
    $credentialLines=$null
    $passwordLine=$null
}
exit $commandExit
