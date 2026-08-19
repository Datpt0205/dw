<#
.SYNOPSIS
    Teleprompter for the DW01 demo — puts each line on the clipboard in turn.

.DESCRIPTION
    The Zalo Bot API can only speak as the bot; it cannot post a message as a
    human. So the requester's own bubble has to come from the requester's own
    Zalo, which means somebody types it. This removes the copy-and-paste:
    press Enter and the next line is on the clipboard, ready for Ctrl+V.

    -Auto goes further and pastes it into whatever window has focus, then
    sends. Click into the right Zalo thread first and do not touch anything
    while it runs — it types into whatever is focused, including your editor.

    Lines come from docs/runbooks/demo-lines.yaml, which is the only place
    they live. The narration in demo-script.md explains them; it does not
    repeat them.

.EXAMPLE
    pwsh scripts/demo_cue.ps1
    pwsh scripts/demo_cue.ps1 -Only chi
    pwsh scripts/demo_cue.ps1 -Auto -From 9
#>
[CmdletBinding()]
param(
    # Paste and send into the focused window instead of only copying.
    [switch]$Auto,
    # Show one person's lines only — useful when two people drive two phones.
    [ValidateSet('an', 'chi')][string]$Only,
    # Resume partway through, 1-based, after a retake.
    [int]$From = 1
)

$ErrorActionPreference = 'Stop'
$linesPath = Join-Path $PSScriptRoot '..\docs\runbooks\demo-lines.yaml'
if (-not (Test-Path $linesPath)) { throw "Không thấy $linesPath" }

# No YAML parser in Windows PowerShell 5.1, and the file is a flat list of
# scalars — read it directly rather than adding a module the demo box may not
# have. Folded (>-) blocks continue on indented lines until the next key.
function Read-DemoLines([string]$Path) {
    $items = @()
    $current = $null
    $folding = $null
    foreach ($raw in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $raw.TrimEnd()
        if ($line -match '^\s*#' -or $line -match '^\s*$') { continue }
        if ($line -match '^\s*-\s+who:\s*(\S+)') {
            if ($current) { $items += $current }
            $current = [ordered]@{ who = $Matches[1]; scene = ''; text = ''; note = ''; wait = 0 }
            $folding = $null
            continue
        }
        if (-not $current) { continue }
        if ($line -match '^\s{4,}(scene|text|note|wait):\s*(.*)$') {
            $key = $Matches[1]
            $val = $Matches[2].Trim()
            if ($val -eq '>-' -or $val -eq '>' -or $val -eq '|') { $folding = $key; continue }
            $folding = $null
            $current[$key] = $val.Trim('"')
            continue
        }
        if ($folding) {
            $chunk = $line.Trim()
            $current[$folding] = ("$($current[$folding]) $chunk").Trim()
        }
    }
    if ($current) { $items += $current }
    return $items
}

$all = Read-DemoLines $linesPath
if ($Only) { $all = $all | Where-Object { $_.who -eq $Only } }
if ($all.Count -eq 0) { throw 'Không có dòng nào khớp bộ lọc.' }

if ($Auto) {
    Add-Type -AssemblyName System.Windows.Forms
    Write-Host ''
    Write-Host '  CHẾ ĐỘ TỰ GÕ — bấm vào đúng khung chat Zalo rồi quay lại đây.' -ForegroundColor Yellow
    Write-Host '  Nó gõ vào CỬA SỔ ĐANG FOCUS. Ctrl+C để dừng.' -ForegroundColor Yellow
}

$colour = @{ an = 'Cyan'; chi = 'Magenta' }
$label = @{ an = 'AN  (người đề nghị)'; chi = 'CHI (trưởng ban)' }
$scene = ''
$index = 0

foreach ($item in $all) {
    $index++
    if ($index -lt $From) { continue }

    if ($item.scene -and $item.scene -ne $scene) {
        $scene = $item.scene
        Write-Host ''
        Write-Host "══ $scene " -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host ("[{0}/{1}] {2}" -f $index, $all.Count, $label[$item.who]) -ForegroundColor $colour[$item.who]
    Write-Host "   $($item.text)" -ForegroundColor White
    if ($item.note) { Write-Host "   · $($item.note)" -ForegroundColor DarkGray }

    Set-Clipboard -Value $item.text

    if ($Auto) {
        Start-Sleep -Milliseconds 700
        [System.Windows.Forms.SendKeys]::SendWait('^v')
        Start-Sleep -Milliseconds 400
        [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
    }
    else {
        Write-Host '   → đã copy. Ctrl+V vào Zalo, Enter. Rồi Enter ở đây để đi tiếp.' -ForegroundColor DarkGray
        [void](Read-Host)
    }

    $wait = [int]$item.wait
    if ($wait -gt 0) {
        Write-Host "   ⏳ chờ $wait giây cho workflow chạy..." -ForegroundColor DarkGray
        Start-Sleep -Seconds $wait
    }
}

Write-Host ''
Write-Host '  Hết kịch bản.' -ForegroundColor Green
