# Render the generated .docx to PDF via Word so we can diff it against the source.
# ASCII-only on purpose: avoids any codepage trouble with CJK filenames.

$ErrorActionPreference = 'Stop'
$dir = 'E:\development\AI-Project'

$docx = Get-ChildItem -LiteralPath $dir -Filter *.docx |
        Where-Object { $_.Name -notlike '~$*' } |
        Select-Object -First 1
if (-not $docx) { throw "no .docx found in $dir" }

$out = Join-Path $dir '_check.pdf'
if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Force }

Write-Output "DOCX : $($docx.Name)"

$word = New-Object -ComObject Word.Application
try {
    $word.Visible = $false
    $word.DisplayAlerts = 0

    $doc = $word.Documents.Open($docx.FullName, $false, $true, $false)
    Write-Output "PAGES: $($doc.ComputeStatistics(2))"

    # 17 = wdExportFormatPDF
    $doc.ExportAsFixedFormat($out, 17)
    $doc.Close($false)
}
finally {
    $word.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    [GC]::Collect()
}

if (Test-Path -LiteralPath $out) {
    Write-Output "OK   : $out ($((Get-Item -LiteralPath $out).Length) bytes)"
} else {
    throw 'export produced no file'
}
