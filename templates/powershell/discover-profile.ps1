[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
ConvertTo-Json -Compress -InputObject ([string]$PROFILE.CurrentUserAllHosts)
