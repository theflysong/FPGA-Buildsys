# PowerShell 5.1 and 7 adapter. Candidate selection belongs to buildsys completion.
Register-ArgumentCompleter -Native -CommandName buildsys, buildsys.bat, buildsys.sh -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    try {
        # Reparse only text before the cursor: later arguments must not affect Tab.
        $text = $commandAst.Extent.Text
        $length = [Math]::Min($text.Length, $cursorPosition - $commandAst.Extent.StartOffset)
        if ($length -le 0) { return }
        $text = $text.Substring(0, $length)
        $parsed = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$null, [ref]$null)
        $command = $parsed.Find({ param($node) $node -is [System.Management.Automation.Language.CommandAst] }, $false)
        if ($null -eq $command) { return }

        $words = New-Object 'System.Collections.Generic.List[string]'
        $elements = $command.CommandElements
        for ($index = 1; $index -lt $elements.Count; $index++) {
            $element = $elements[$index]
            # Read literal AST values, never evaluate expressions during completion.
            if ($element -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
                $words.Add($element.Value)
            } elseif ($element -is [System.Management.Automation.Language.CommandParameterAst]) {
                $words.Add($element.Extent.Text)
            } elseif ($element -is [System.Management.Automation.Language.ConstantExpressionAst]) {
                $words.Add([string]$element.Value)
            } else {
                return
            }
        }
        if ($elements.Count -eq 1 -or $elements[-1].Extent.EndOffset -lt $text.Length -or
            $cursorPosition -gt $commandAst.Extent.EndOffset) {
            $words.Add('')
        }

        $executables = @(Get-Command -Name $commandAst.GetCommandName() -CommandType Application, ExternalScript -ErrorAction Stop)
        $executable = $executables[0].Path
        # On Windows use the batch sibling for both extensionless and .sh
        # entry points; invoking either file directly may open its association.
        if ([IO.Path]::DirectorySeparatorChar -eq '\' -and
            ([IO.Path]::GetExtension($executable) -eq '' -or $executable.EndsWith('.sh'))) {
            $batch = [IO.Path]::ChangeExtension($executable, '.bat')
            if (-not (Test-Path -LiteralPath $batch)) { return }
            $executable = $batch
        }
        $json = ConvertTo-Json -InputObject @($words.ToArray()) -Compress
        # Keep the JSON transport ASCII-compatible on PowerShell 5.1 and 7.
        $json = [regex]::Replace($json, '[^\x00-\x7f]', {
            param($match) '\u{0:x4}' -f [int][char]$match.Value
        })
        # A native PowerShell pipeline shares the interactive console. The
        # wrapper's venv activation invokes chcp, which can clear the terminal
        # during PSReadLine completion. Give the query its own redirected pipes
        # and no console, including when cmd.exe runs the Windows batch file.
        $startInfo = New-Object System.Diagnostics.ProcessStartInfo
        $startInfo.UseShellExecute = $false
        $startInfo.CreateNoWindow = $true
        $startInfo.RedirectStandardInput = $true
        $startInfo.RedirectStandardOutput = $true
        $startInfo.RedirectStandardError = $true
        $startInfo.WorkingDirectory = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath('.')
        if ([IO.Path]::DirectorySeparatorChar -eq '\') {
            $startInfo.FileName = $env:ComSpec
            $startInfo.Arguments = '/d /s /c ""' + $executable + '" completion --json"'
        } else {
            $startInfo.FileName = $executable
            $startInfo.Arguments = 'completion --json'
        }
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $startInfo
        try {
            $null = $process.Start()
            # Drain both pipes concurrently so diagnostics cannot block stdout.
            $stdout = $process.StandardOutput.ReadToEndAsync()
            $stderr = $process.StandardError.ReadToEndAsync()
            $process.StandardInput.WriteLine($json)
            $process.StandardInput.Close()
            $process.WaitForExit()
            $output = $stdout.GetAwaiter().GetResult()
            $null = $stderr.GetAwaiter().GetResult()
            if ($process.ExitCode -ne 0) { return }
        } finally {
            $process.Dispose()
        }
        $candidates = ConvertFrom-Json -InputObject $output -ErrorAction Stop
        foreach ($candidate in $candidates) {
            $completion = [string]$candidate
            $kind = [System.Management.Automation.CompletionResultType]::ParameterValue
            if ($completion.EndsWith('/')) {
                $kind = [System.Management.Automation.CompletionResultType]::ProviderContainer
            }
            if ($completion -match '[\s''"`$&;(){}\[\]|<>@#]') {
                $completion = "'" + $completion.Replace("'", "''") + "'"
            }
            [System.Management.Automation.CompletionResult]::new($completion, [string]$candidate, $kind, [string]$candidate)
        }
    } catch {
        # Missing commands or malformed input should never interrupt interactive Tab.
        return
    }
}
