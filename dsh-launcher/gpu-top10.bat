@echo off
chcp 65001 >nul
title GPU Top 10 by Dedicated VRAM
echo.
echo Sampling GPU dedicated memory per process (a few seconds)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$cs = Get-Counter -Counter '\GPU Process Memory(*)\Dedicated Usage' -SampleInterval 1 -MaxSamples 2; $rows = foreach ($s in $cs.CounterSamples) { $m = [regex]::Match($s.InstanceName, 'pid_(\d+)'); if ($m.Success) { [PSCustomObject]@{ PId=[int]$m.Groups[1].Value; Bytes=[long]$s.CookedValue } } }; $top = $rows | Group-Object PId | ForEach-Object { [PSCustomObject]@{ PId=[int]$_.Name; MB=[math]::Round((($_.Group | Measure-Object Bytes -Max).Maximum)/1MB,1) } } | Sort-Object MB -Descending | Select-Object -First 10; Write-Host 'Rank  PID    MB          Process (Path)'; Write-Host '----  ------ -----------  ----------------------------------------'; $i = 1; foreach ($t in $top) {   $p = Get-Process -Id $t.PId -ErrorAction SilentlyContinue;   $n = if ($p) { $p.ProcessName } else { 'pid_' + $t.PId };   $path = if ($p) { $p.Path } else { '' };   Write-Host ('{0,-5} {1,-6} {2,8} MB  {3}  {4}' -f $i, $t.PId, $t.MB, $n, $path);   $i++ }"
echo.
pause