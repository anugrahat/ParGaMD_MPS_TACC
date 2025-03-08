#!/bin/bash
set -x
umask g+r

# Arguments handling
RUN_DIR="$1"
cd "$RUN_DIR" || exit 1
shift
export WEST_JOBID=$1
shift
export SLURM_NODENAME=$1
shift
export CUDA_VISIBLE_DEVICES_ALLOCATED=$1
shift

# Load environment
source env.sh

# Simply set CUDA_VISIBLE_DEVICES but do NOT enable MPS
export CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES_ALLOCATED"
echo "Node $SLURM_NODENAME using GPUs: $CUDA_VISIBLE_DEVICES"

# Optional GPU info for debugging
nvidia-smi

# Run WESTPA
w_run "$@" &> "west-$SLURM_NODENAME-node.log"

exit $?
