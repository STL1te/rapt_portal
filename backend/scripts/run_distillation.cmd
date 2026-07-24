@echo off
rem Recipe-wizard eval / distillation run. LLM settings come from backend\.env.
rem Output is a FIXED persistent dataset: reruns skip ready schemas and retry errors.
rem
rem Usage (only sampling flags, never an output path):
rem   run_distillation.cmd                     - first 36 recipes
rem   run_distillation.cmd --count 200         - first 200 (superset of a smaller count)
rem   run_distillation.cmd --shuffle 42 --count 50  - random 50 (seed 42, reproducible)
rem   run_distillation.cmd --indices 222 6103  - specific recipes
setlocal
cd /d "%~dp0.."

set PYTHONPATH=.
set CORPUS=D:\Work\projects\beer_recipes_data\recipes_detail.jsonl
set OUTPUT=D:\Work\projects\beer_recipes_data\distill.jsonl

set ARGS=%*
if "%~1"=="" set ARGS=--count 36 --concurrency 3

echo Corpus: %CORPUS%
echo Output: %OUTPUT%
uv run python scripts\evaluate_recipe_wizard.py "%CORPUS%" "%OUTPUT%" %ARGS%
