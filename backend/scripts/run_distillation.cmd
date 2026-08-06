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

rem Teacher endpoint: overrides the local WIZARD_LLM_* from .env (real env beats
rem load_dotenv). Key is NOT here - it comes from LLM_API_KEY in .env (gitignored),
rem so WIZARD_LLM_API_KEY must stay commented out there.
rem Extraction is not a reasoning task: flash beat qwen3.7-max here (max truncated long
rem recipes and its thinking judge rejected its own correct output). The token-plan
rem endpoint (token-plan.ap-southeast-1.maas.aliyuncs.com) does NOT serve qwen3.7-flash.
set WIZARD_LLM_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
set WIZARD_LLM_MODEL=qwen3.7-flash
set WIZARD_LLM_RESPONSE_FORMAT=json_schema
set WIZARD_LLM_SAMPLING=default

set PYTHONPATH=.
set CORPUS=D:\Work\projects\beer_knowledge\data\raw\recipes_detail.jsonl
set OUTPUT=D:\Work\projects\beer_knowledge\data\distil\v2\distill.jsonl
rem EN corpus (use the same --shuffle seed as the previous EN run to keep subsets nested):
rem set CORPUS=D:\Work\projects\beer_knowledge\data\raw\beersfriend_detail.jsonl
rem set OUTPUT=D:\Work\projects\beer_knowledge\data\distil\v2\distill_en.jsonl

set ARGS=%*
if "%~1"=="" set ARGS=--count 36 --concurrency 3

echo Corpus: %CORPUS%
echo Output: %OUTPUT%
uv run python scripts\evaluate_recipe_wizard.py "%CORPUS%" "%OUTPUT%" %ARGS%
