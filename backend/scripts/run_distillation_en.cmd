@echo off
rem English-corpus (Brewer's Friend) variant of run_distillation.cmd.
rem Separate OUTPUT is required: resume/--skip-errors key on indices of THIS corpus.
setlocal
cd /d "%~dp0.."

set PYTHONPATH=.
set CORPUS=D:\Work\projects\beer_knowledge\data\beersfriend_detail.jsonl
set OUTPUT=D:\Work\projects\beer_recipes_data\distill_en.jsonl

set ARGS=%*
if "%~1"=="" set ARGS=--count 36 --concurrency 3

echo Corpus: %CORPUS%
echo Output: %OUTPUT%
uv run python scripts\evaluate_recipe_wizard.py "%CORPUS%" "%OUTPUT%" %ARGS%
