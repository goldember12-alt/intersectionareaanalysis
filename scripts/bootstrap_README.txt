# Bootstrap Instructions for IntersectionCrashAnalysis

Preferred entrypoint:
- `.\scripts\bootstrap.cmd`

Underlying implementation:
- `scripts/bootstrap.ps1`

The wrapper is the default entry story because direct `.\scripts\bootstrap.ps1` execution may be blocked by PowerShell execution policy.

Bootstrap does three main things:
1. moves TEMP/TMP outside the repo
2. moves pip cache outside the repo
3. optionally creates either a repo-local or external virtual environment

Current practical defaults:
- base Python 3.11
- external TEMP/TMP
- external pip cache
- external interpreter or external venv is allowed and preferred

Recommended commands:
- `.\scripts\bootstrap.cmd`
- `.\scripts\bootstrap.cmd -CreateVenv -UseExternalVenv`
- `.\scripts\bootstrap.cmd -CreateVenv -UseExternalVenv -InstallDeps`

Codex guidance:
- use the interpreter path emitted by bootstrap
- do not assume `.\.venv\Scripts\python.exe`
- do not create a repo-local `.venv` when external venv mode is already in use unless explicitly instructed
