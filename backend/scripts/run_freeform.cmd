@echo off
rem Free-form rewrite run over accepted distillation rows, RU then EN. Rewriter =
rem REWRITER_LLM_* below (key/base_url fall back to the LLM_* block in backend\.env,
rem which must point at the pay-as-you-go DashScope endpoint); semantic gate =
rem WIZARD_LLM_* (same judge as run_distillation.cmd). Output is persistent: reruns
rem skip ok rows, retry rejected. Extra args are appended to both runs and win over
rem the built-in counts (argparse keeps the last occurrence).
rem
rem   run_freeform.cmd              - full rewrites, RU 1000 / EN 500
rem   run_freeform.cmd --partial    - partial drafts into freeform_partial_*, RU 500 / EN 250
setlocal
cd /d "%~dp0.."

rem Judge - same as run_distillation.cmd: the gate must match the corpus it joins.
set WIZARD_LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
set WIZARD_LLM_MODEL=qwen3.7-flash
set WIZARD_LLM_RESPONSE_FORMAT=json_schema
set WIZARD_LLM_SAMPLING=default
rem Pinned for the same reason as run_distillation.cmd: the judge is a cloud model and
rem must not inherit the student's short prompt from .env.
set WIZARD_LLM_PROMPT=full

rem Rewriter: stronger model; thinking off - it shares the completion budget and
rem truncates long recipes.
set REWRITER_LLM_MODEL=qwen3.7-max
set REWRITER_LLM_SAMPLING=default
set REWRITER_LLM_EXTRA_BODY={"enable_thinking": false}

set PYTHONPATH=.
set DATA=D:\Work\projects\beer_knowledge\data
set TEACHER=%DATA%\distil\qwen3.7-flash
rem The frozen test set is the cross-iteration comparison point: never rewrite its rows,
rem or a paraphrase of a held-out recipe lands in train.
set EXCLUDE=--exclude "%DATA%\sft\frozen\test.jsonl"

rem Partial drafts carry CUT specs as targets - they must not land in the full-rewrite file.
set SUFFIX=
set RU_COUNT=1000
set EN_COUNT=500
rem one-line ifs, not a parenthesized block: cmd mis-parses multi-line blocks in
rem LF-only files and would silently fall through to the full-run counts.
if /i "%~1"=="--partial" set SUFFIX=_partial
if /i "%~1"=="--partial" set RU_COUNT=500
if /i "%~1"=="--partial" set EN_COUNT=250

uv run python scripts\freeform_rewrite.py "%TEACHER%\ru.jsonl" "%DATA%\raw\recipes_detail.jsonl" "%TEACHER%\freeform%SUFFIX%_ru.jsonl" %EXCLUDE% --count %RU_COUNT% --concurrency 96 %*
uv run python scripts\freeform_rewrite.py "%TEACHER%\en.jsonl" "%DATA%\raw\beersfriend_detail.jsonl" "%TEACHER%\freeform%SUFFIX%_en.jsonl" %EXCLUDE% --count %EN_COUNT% --concurrency 96 %*
