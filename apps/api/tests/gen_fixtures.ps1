# Generuje fixtury audio testów przez Windows SAPI TTS (16 kHz, mono, PCM16).
# Uruchamiane automatycznie z conftest.py, gdy fixtur brakuje.

$dir = Join-Path $PSScriptRoot "fixtures"
New-Item -ItemType Directory -Force $dir | Out-Null

Add-Type -AssemblyName System.Speech
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
    16000,
    [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
    [System.Speech.AudioFormat.AudioChannel]::Mono
)

function Speak-ToFile($path, $text) {
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.SetOutputToWaveFile($path, $fmt)
    $synth.Speak($text)
    $synth.SetOutputToNull()
    $synth.Dispose()
    Write-Host "OK: $path"
}

# krótka fraza bez interpunkcji - bez wewnętrznych pauz TTS
Speak-ToFile (Join-Path $dir "phrase.wav") "she sells fresh flowers at the market every single morning"

# dłuższa ciągła wypowiedź
Speak-ToFile (Join-Path $dir "speech.wav") "the quick brown fox jumps over the lazy dog and keeps running through the quiet forest without stopping even once"

# wypowiedź z wypełniaczami i powtórzeniami - do testu dysfluencji Whispera
Speak-ToFile (Join-Path $dir "disfluent.wav") "Um, so I was, uh, I was thinking that we could, you know, we could try it again. I mean, it's, it's not really that simple, right?"
