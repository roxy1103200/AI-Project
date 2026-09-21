# Convert the resume PDF to an editable Word document using Word COM automation.
# Deliberately avoids non-ASCII literals so the script survives any codepage.

$ErrorActionPreference = 'Stop'
$dir = 'E:\development\AI-Project'

$pdf = Get-ChildItem -LiteralPath $dir -Filter *.pdf |
       Where-Object { $_.Name -notlike '~$*' } |
       Sort-Object Length -Descending |
       Select-Object -First 1

if (-not $pdf) { throw "No source PDF found in $dir" }

$out = Join-Path $dir ($pdf.BaseName + '.docx')
Write-Output "SOURCE : $($pdf.FullName)"
Write-Output "TARGET : $out"

$word = New-Object -ComObject Word.Application
try {
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.Options.DoNotPromptForConvert = $true
    $word.Options.ConfirmConversions = $false

    # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles)
    $doc = $word.Documents.Open($pdf.FullName, $false, $false, $false)

    # 16 = wdFormatDocumentDefault (.docx)
    $doc.SaveAs2($out, 16)

    $pages = $doc.ComputeStatistics(2)   # 2 = wdStatisticPages
    $words = $doc.ComputeStatistics(0)   # 0 = wdStatisticWords
    Write-Output "PAGES  : $pages"
    Write-Output "WORDS  : $words"

    $doc.Close($false)
}
finally {
    $word.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    [GC]::Collect()
}

if (Test-Path -LiteralPath $out) {
    Write-Output "OK -> $out"
    Write-Output "BYTES: $((Get-Item -LiteralPath $out).Length)"
} else {
    throw 'Conversion produced no output file.'
}
