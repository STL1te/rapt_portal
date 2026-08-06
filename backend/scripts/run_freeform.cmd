@echo off
rem Free-form rewrite run over accepted distillation rows, RU then EN. LLM settings from
rem backend\.env (must point at the frontier). Output is persistent: reruns skip ok rows,
rem retry rejected. --count applies to each corpus separately.
rem
rem Usage:
rem   run_freeform.cmd                 - first 50 accepted rows of each corpus
rem   run_freeform.cmd --count 300     - first 300 of each (superset of a smaller count)
setlocal
cd /d "%~dp0.."

rem Same teacher as run_distillation.cmd - the rewrites must match the corpus they join.
set WIZARD_LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
set WIZARD_LLM_MODEL=qwen3.7-flash
set WIZARD_LLM_RESPONSE_FORMAT=json_schema
set WIZARD_LLM_SAMPLING=default

set PYTHONPATH=.
set DATA=D:\Work\projects\beer_knowledge\data
set TEACHER=%DATA%\distil\qwen3.7-flash
rem The frozen test set is the cross-iteration comparison point: never rewrite its rows,
rem or a paraphrase of a held-out recipe lands in train.
set EXCLUDE=--exclude "%DATA%\sft\frozen\test.jsonl"

set ARGS=%*
if "%~1"=="" set ARGS=--count 50 --concurrency 3

uv run python scripts\freeform_rewrite.py "%TEACHER%\ru.jsonl" "%DATA%\raw\recipes_detail.jsonl" "%TEACHER%\freeform_ru.jsonl" %EXCLUDE% %ARGS%
uv run python scripts\freeform_rewrite.py "%TEACHER%\en.jsonl" "%DATA%\raw\beersfriend_detail.jsonl" "%TEACHER%\freeform_en.jsonl" %EXCLUDE% %ARGS%
