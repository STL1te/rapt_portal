@echo off
rem Free-form rewrite run over accepted distillation rows, RU then EN. LLM settings from
rem backend\.env (must point at the frontier). Output is persistent: reruns skip ok rows,
rem retry rejected. --count applies to each corpus separately (EN caps at ~430 accepted).
rem
rem Usage:
rem   run_freeform.cmd                 - first 50 accepted rows of each corpus
rem   run_freeform.cmd --count 300     - first 300 of each (superset of a smaller count)
setlocal
cd /d "%~dp0.."

set PYTHONPATH=.
set DATA=D:\Work\projects\beer_knowledge\data
set EXCLUDE=--exclude "%DATA%\sft_distil\val.jsonl" "%DATA%\sft_distil\test.jsonl"

set ARGS=%*
if "%~1"=="" set ARGS=--count 50 --concurrency 3

@REM uv run python scripts\freeform_rewrite.py "%DATA%\distil\distill.jsonl" "%DATA%\recipes_detail.jsonl" "%DATA%\distil\freeform.jsonl" %EXCLUDE% %ARGS%
uv run python scripts\freeform_rewrite.py "%DATA%\distil\distill_en.jsonl" "%DATA%\beersfriend_detail.jsonl" "%DATA%\distil\freeform_en.jsonl" %EXCLUDE% %ARGS%
