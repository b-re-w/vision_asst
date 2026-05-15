#!/bin/bash
# Launch the vision-asst FastAPI server.
#
# Single-process design: FastAPI's lifespan starts the embedded vllm-omni
# AsyncLLMEngine on both GPUs (CUDA_VISIBLE_DEVICES=0,1). The WebSocket
# endpoint becomes available at ws://<host>:<port>/ws once /health returns
# 200.
#
# Usage:
#   ./run.sh [--host HOST] [--port PORT] [--model MODEL]

set -e

# flashinfer JIT cache (used by Qwen3-Omni for fused attention kernels)
export FLASHINFER_CACHE_DIR="$(dirname "$0")/.flashinfer"
export CUDA_HOME=${CUDA_HOME:-/usr/local/cuda}
export CPATH=$CUDA_HOME/include:$CPATH
export VLLM_OMNI_STAGE_INIT_TIMEOUT=${VLLM_OMNI_STAGE_INIT_TIMEOUT:-7200}
export VLLM_STAGE_INIT_TIMEOUT=${VLLM_STAGE_INIT_TIMEOUT:-7200}
export PYTORCH_CUDA_ALLOC_CONF=${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}
export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-0,1}
export HF_HUB_ENABLE_HF_TRANSFER=1
# Cutlass C3x FP8 GEMM doesn't dispatch on Blackwell (SM 12.0); force fallback.
export VLLM_DISABLED_KERNELS=${VLLM_DISABLED_KERNELS:-CutlassFp8BlockScaledMMKernel,CutlassFP8ScaledMMLinearKernel}


# Defaults map to Settings() / VA_* env vars.
HOST="${VA_HOST:-0.0.0.0}"
PORT="${VA_PORT:-8070}"
MODEL="${VA_MODEL:-Qwen/Qwen3-Omni-30B-A3B-Instruct}"
MODEL="${VA_MODEL:-marksverdhei/Qwen3-Omni-30B-A3B-FP8}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --host)        HOST="$2"; shift 2 ;;
        --port)        PORT="$2"; shift 2 ;;
        --model)       MODEL="$2"; shift 2 ;;
        --help)
            cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --host HOST       Bind host (default: 0.0.0.0)
  --port PORT       Bind port (default: 8000)
  --model MODEL     Model id or path (default: Qwen/Qwen3-Omni-30B-A3B-Instruct)
  --help            Show this help message

Endpoints:
  GET  /health      Engine status (503 while loading, 200 once ready)
  GET  /info        Configuration snapshot
  WS   /ws          Bidirectional audio/video streaming session
EOF
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage."
            exit 1
            ;;
    esac
done

export VA_HOST="$HOST"
export VA_PORT="$PORT"
export VA_MODEL="$MODEL"

echo "=========================================="
echo "Starting vision-asst"
echo "=========================================="
echo "Model:  $MODEL"
echo "Bind:   http://$HOST:$PORT"
echo "GPUs:   $CUDA_VISIBLE_DEVICES"
echo "=========================================="

exec uv run python -m vision_asst
