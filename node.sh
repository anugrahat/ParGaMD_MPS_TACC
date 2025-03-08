#!/bin/bash
set -x
umask g+r

##############################################################################
# 1) Parse arguments
##############################################################################
RUN_DIR="$1"
cd "$RUN_DIR" || exit 1
shift

export WEST_JOBID="$1"
shift

export SLURM_NODENAME="$1"
shift

export CUDA_VISIBLE_DEVICES_ALLOCATED="$1"
shift

##############################################################################
# 2) Load your environment
##############################################################################
# Make sure you have the same conda/module environment that the master does.
# If 'env.sh' already loads modules and activates your 'openmm_env', that is fine.
# Otherwise, do something like:
#   source ~/.bashrc
#   conda activate openmm_env
source env.sh

##############################################################################
# 3) MPS setup (if needed; otherwise consider removing)
##############################################################################
IFS=',' read -ra NODE_GPUS <<< "$CUDA_VISIBLE_DEVICES_ALLOCATED"
for gpuid in "${NODE_GPUS[@]}"; do
    export CUDA_MPS_PIPE_DIRECTORY="/tmp/nvidia-mps-$WEST_JOBID-$gpuid"
    export CUDA_MPS_LOG_DIRECTORY="/tmp/nvidia-log-$WEST_JOBID-$gpuid"
    mkdir -p "$CUDA_MPS_PIPE_DIRECTORY" "$CUDA_MPS_LOG_DIRECTORY"

    # Start MPS for this GPU
    CUDA_VISIBLE_DEVICES="$gpuid" nvidia-cuda-mps-control -d
done

# Restore the full GPU list
export CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES_ALLOCATED"
echo "Node: $SLURM_NODENAME using GPUs: $CUDA_VISIBLE_DEVICES"
nvidia-smi

##############################################################################
# 4) Launch the ZMQ worker(s)
##############################################################################
# "$@" is whatever extra args were passed by the submission script
# For example: --n-workers=N --zmq-mode=client --zmq-read-host-info=...
w_run "$@" &> "west-$SLURM_NODENAME-node.log"

##############################################################################
# 5) Cleanup MPS on exit
##############################################################################
for gpuid in "${NODE_GPUS[@]}"; do
    export CUDA_VISIBLE_DEVICES="$gpuid"
    echo "Stopping MPS for GPU $gpuid"
    echo quit | nvidia-cuda-mps-control
done

exit $?
