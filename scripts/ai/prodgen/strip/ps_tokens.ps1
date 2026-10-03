$ErrorActionPreference = 'Stop'
$b64 = [Console]::In.ReadToEnd()
$raw = [System.Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64.Trim()))
$items = ConvertFrom-Json -InputObject $raw
$results = New-Object System.Collections.ArrayList
foreach ($text in @($items)) {
    $tokens = $null
    $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseInput([string]$text, [ref]$tokens, [ref]$errors)
    $list = New-Object System.Collections.ArrayList
    foreach ($t in $tokens) {
        if ($t.Kind -eq 'Comment') { continue }
        [void]$list.Add(@([string]$t.Kind, [string]$t.Text))
    }
    $errCount = 0
    if ($errors) { $errCount = @($errors).Count }
    [void]$results.Add(@{ tokens = $list; errors = $errCount })
}
$json = ConvertTo-Json -InputObject $results -Depth 6 -Compress
[Console]::Out.Write([Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($json)))
