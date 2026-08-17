"""Merge the LoRA into the base, build a domain imatrix, and cut the low GGUF quants.

Upstream publishes no importance matrix for this base, so Unsloth's auto-download has
nothing to fetch and IQ2/IQ3 are unusable without one — we compute our own. Calibration
text comes from the v6 train split rather than a generic corpus: this model only ever sees
recipe extraction under one system prompt, so that is the distribution worth protecting.

There is no merged fp16 checkpoint anywhere — only the base in the HF cache volume and a
319 MB adapter. Merging happens through llama.cpp rather than peft so it never needs the
52 GB of RAM a transformers merge would.

Everything runs inside the official llama.cpp image; nothing is installed on the host.
Only the imatrix pass touches the GPU — offload what fits with --gpu-layers, the rest runs
on CPU. Conversion, merging and quantization are CPU- and disk-bound.

Each stage skips itself if its output is already there, so a failure four hours in does not
redo the conversion.

Usage (from backend/). --base-mount is the HF cache volume, --out-mount holds everything
this writes (~150 GB: base F16, merged F16, then the quants):
  uv run python scripts\\quantize_low.py --base-mount unsloth-local_hf-cache:/model ^
    --out-mount D:\\Work\\quants:/out --gpu-layers 20
  uv run python scripts\\quantize_low.py --base-mount ... --out-mount ... --dry-run
"""

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

IMAGE = "ghcr.io/ggml-org/llama.cpp:full-cuda"
# Neither published image ships llama-export-lora, so the merge runs a binary built from
# the llama.cpp source Unsloth already keeps in its volume (same b10360 as its prebuilts).
BUILD_IMAGE = "stl1te/unsloth-studio:latest"
EXPORT_LORA = "/out/build-lora/bin/llama-export-lora"

# Sized for a 12 GB card, which is what actually blocks the 27B from replacing the 12B.
# Q3_K_M is over that budget but kept as the quality reference the small ones are judged
# against — if IQ3 tracks it, the drop is quantization, not the model.
QUANTS = ("Q3_K_M", "IQ3_XXS", "Q2_K", "IQ2_M")


def build_corpus(train_set: Path, target: Path, examples: int) -> None:
    """Render training examples back into flat text for llama-imatrix.

    The full turn is kept — system, user and the JSON answer — because the activations we
    want to measure are the ones that produce the spec, not just the ones that read it."""
    rows = [
        json.loads(line)
        for line in train_set.read_text(encoding="utf-8").split("\n")
        if line.strip()
    ]
    random.Random(3407).shuffle(rows)  # same seed the training runs use
    chunks = [
        "\n".join(message["content"] for message in row["messages"])
        for row in rows[:examples]
    ]
    assert chunks, f"no examples read from {train_set}"
    target.write_text("\n\n".join(chunks), encoding="utf-8")
    print(f"corpus: {len(chunks)} examples, {target.stat().st_size / 1e6:.1f} MB")


def docker(
    args: argparse.Namespace,
    command: str,
    gpu: bool = False,
    image: str = IMAGE,
    capture: bool = False,
) -> str:
    """Stages stream their output — these steps run for hours and a silent log is
    indistinguishable from a hung one. Only the probe captures, since it is parsed."""
    run = ["docker", "run", "--rm"]
    if gpu:
        run += ["--gpus", "all"]
    run += ["-v", args.base_mount, "-v", args.out_mount]
    run += ["--entrypoint", "sh", image, "-c", command]
    if args.dry_run:
        print("  $ " + " ".join(run[:-1]) + f" '{command}'")
        return ""
    done = subprocess.run(run, text=True, capture_output=capture)
    if done.returncode:
        sys.exit(f"docker failed:\n{(done.stdout or '')[-3000:]}\n{(done.stderr or '')[-3000:]}")
    return (done.stdout or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-mount", required=True, help="HF cache volume, e.g. vol:/model")
    parser.add_argument("--out-mount", required=True, help="work dir, e.g. D:\\Work\\quants:/out")
    parser.add_argument("--base-repo", default="unsloth--Qwen3.8-27B")
    parser.add_argument("--adapter", default="/out/adapter", help="path inside the container")
    parser.add_argument("--name", default="brewmind-qwen3.8-27b")
    parser.add_argument(
        "--train-set",
        type=Path,
        default=Path(r"D:\Work\projects\beer_knowledge\data\sft\v6\train.jsonl"),
    )
    parser.add_argument("--examples", type=int, default=150)
    parser.add_argument("--gpu-layers", type=int, default=20, help="offload what fits in VRAM")
    parser.add_argument("--ctx", type=int, default=2048)
    parser.add_argument("--quants", nargs="+", default=list(QUANTS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    host_out = Path(args.out_mount.rsplit(":", 1)[0])
    build_corpus(args.train_set, host_out / "imatrix_corpus.txt", args.examples)

    # Resolve tools and the snapshot dir inside the container instead of assuming a layout:
    # the image moves binaries between releases and the cache path carries a commit hash.
    if not args.dry_run:
        # The published image keeps its binaries in /app, which is not on PATH.
        probe = docker(
            args,
            "for f in /app/llama-imatrix /app/llama-quantize /app/convert_hf_to_gguf.py "
            f"  /app/convert_lora_to_gguf.py {EXPORT_LORA}; do "
            "  [ -f $f ] || echo MISSING:$f; done; "
            f"ls -d /model/hub/models--{args.base_repo}/snapshots/*/",
            capture=True,
        )
        print(probe)
        if "MISSING:" in probe:
            sys.exit(
                f"missing tools:\n{probe}\n"
                f"(build {EXPORT_LORA} first — see the module docstring)"
            )
        snapshot = next((l for l in probe.split() if "/snapshots/" in l), None)
        if not snapshot:
            sys.exit(f"base snapshot not found for {args.base_repo}:\n{probe}")
    else:
        snapshot = f"/model/hub/models--{args.base_repo}/snapshots/*/"

    base_gguf, adapter_gguf = "/out/base-f16.gguf", "/out/adapter.gguf"
    merged = f"/out/{args.name}-f16.gguf"

    def stage(
        label: str, produces: str, command: str, gpu: bool = False, image: str = IMAGE
    ) -> None:
        if (host_out / produces.removeprefix("/out/")).exists() and not args.dry_run:
            print(f"-> {label}: already there, skipping")
            return
        print(f"-> {label}", flush=True)
        docker(args, command, gpu=gpu, image=image)

    stage(
        "base -> F16 GGUF (~52 GB)",
        base_gguf,
        f"python3 /app/convert_hf_to_gguf.py {snapshot} --outtype f16 --outfile {base_gguf}",
    )
    stage(
        "adapter -> GGUF",
        adapter_gguf,
        f"python3 /app/convert_lora_to_gguf.py --base {snapshot} --outtype f16 "
        f"--outfile {adapter_gguf} {args.adapter}",
    )
    stage(
        "merge LoRA into base",
        merged,
        f"LD_LIBRARY_PATH=/out/build-lora/bin {EXPORT_LORA} "
        f"-m {base_gguf} --lora {adapter_gguf} -o {merged}",
        image=BUILD_IMAGE,
    )
    stage(
        f"imatrix ({args.examples} examples, -ngl {args.gpu_layers})",
        f"/out/{args.name}.imatrix",
        # --no-mmap is not optional here: /out is a Windows bind mount (drvfs), and mmap of
        # a 54 GB file over it hangs the loader outright — no I/O, no progress, no error.
        # The conversion and merge stages are unaffected because they use plain read/write.
        f"/app/llama-imatrix -m {merged} -f /out/imatrix_corpus.txt --no-mmap "
        f"-o /out/{args.name}.imatrix -ngl {args.gpu_layers} -c {args.ctx}",
        gpu=True,
    )
    for quant in args.quants:
        stage(
            f"{quant} (CPU, no VRAM needed)",
            f"/out/{args.name}-{quant}.gguf",
            # blk.64 is the MTP (nextn) block. Inference ignores it — "model has unused
            # tensor blk.64.* -- ignoring" — so the imatrix pass never records weights for
            # it, and the very low-bit quants refuse to guess and bail at tensor 852/866.
            # Pinning that one block to q8_0 sidesteps it for ~0.3 GB; the k-quants above
            # IQ3 never hit this because they tolerate a missing matrix.
            f"/app/llama-quantize --imatrix /out/{args.name}.imatrix "
            f"--tensor-type blk.64=q8_0 {merged} /out/{args.name}-{quant}.gguf {quant}",
        )

    print("\nDone. Sizes prove nothing — measure:")
    print("  uv run python scripts/eval_sft_test.py <v6 test> <out.jsonl> --model <id>")


if __name__ == "__main__":
    main()
