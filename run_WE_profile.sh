#!/bin/bash
#SBATCH --job-name=gamd_run
#SBATCH --account=ahnlab
#SBATCH --partition=gpu-ahn
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --gres=gpu:2
#SBATCH --time=120:00:00

# We add the standard module loads here
module load conda3/4.X
module load cuda/11.8.0
source activate openmm_env

# Now we invoke 'nsys profile' on an *inline script*, which is everything
# you previously had in run_WE_multi.sh. We'll pass that inline content
# via 'bash -c "...the script..."'.
# '<<EOF' is a "here-document" that ends at 'EOF'.

nsys profile --stats=true -o my_profile --trace=cuda,nvtx,osrt bash -c '
##############################################################################
# 0) Basic environment and module loads
##############################################################################
set -x
cd "$SLURM_SUBMIT_DIR"

echo "Initially, CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
nvidia-smi -L

##############################################################################
# 1) (Optional) Start MPS
##############################################################################
nvidia-cuda-mps-control -d
sleep 5
echo set_active_thread_percentage 40 | nvidia-cuda-mps-control

##############################################################################
# 2) Initialize WESTPA
##############################################################################
source env.sh || exit 1
export SERVER_INFO="${SLURM_SUBMIT_DIR}/west_zmq_info.json"

# Tweak ZMQ heartbeat/timeouts if needed
export WM_ZMQ_MASTER_HEARTBEAT=50
export WM_ZMQ_WORKER_HEARTBEAT=50
export WM_ZMQ_TIMEOUT_FACTOR=100

##############################################################################
# 3) Start w_run (ZMQ master) in the background
##############################################################################
w_run --work-manager=zmq \
      --n-workers=0 \
      --zmq-mode=master \
      --zmq-write-host-info="$SERVER_INFO" \
      --zmq-comm-mode=tcp \
      &> "west-${SLURM_JOB_ID}-master.log" &

# Wait up to 60s for server info
for ((n=0; n<60; n++)); do
   if [ -e "$SERVER_INFO" ]; then
       cat "$SERVER_INFO"
       break
   fi
   sleep 1
done
if [ ! -e "$SERVER_INFO" ]; then
   echo "ERROR: ZMQ master did not start properly."
   exit 1
fi

##############################################################################
# 4) Start BOTH GPU usage loggers in the background
##############################################################################
SM_LOG="gpu_dmon_${SLURM_JOB_ID}.log"
echo "Logging SM usage to $SM_LOG (every 10s)"
nvidia-smi dmon -s u -d 10 > "$SM_LOG" &
DMON_PID=$!

MEM_LOG="gpu_query_${SLURM_JOB_ID}.log"
echo "Logging memory/overall usage to $MEM_LOG (every 10s)"
nvidia-smi --query-gpu=timestamp,index,name,utilization.gpu,utilization.memory,memory.total,memory.used \
           --format=csv -l 10 > "$MEM_LOG" &
QPID=$!

##############################################################################
# 5) Launch GPU workers
##############################################################################
export WORKERS_PER_GPU=12
IFS="," read -ra DEVICES <<< "$CUDA_VISIBLE_DEVICES"
total_workers=$(( ${#DEVICES[@]} * WORKERS_PER_GPU ))
echo "Debug: DEVICES = ${DEVICES[@]}"
echo "Debug: total_workers = $total_workers"

for gpuid in "${DEVICES[@]}"; do
    for ((w=1; w<=WORKERS_PER_GPU; w++)); do
        (
          export CUDA_VISIBLE_DEVICES="$gpuid"
          w_run --work-manager=zmq \
                --n-workers=1 \
                --zmq-mode=client \
                --zmq-read-host-info="$SERVER_INFO" \
                --zmq-comm-mode=tcp \
                &> "west-${SLURM_JOB_ID}-worker-gpu${gpuid}-w${w}.log"
        ) &
    done
done

# Wait for all workers + master
wait

##############################################################################
# 6) Kill the logging processes
##############################################################################
echo "Killing dmon..."
kill $DMON_PID 2>/dev/null

echo "Killing nvidia-smi query..."
kill $QPID 2>/dev/null

##############################################################################
# 7) Clean up MPS
##############################################################################
echo "Stopping MPS..."
echo quit | nvidia-cuda-mps-control

echo "Run complete."
exit 0
# End of inline script
##############################################################################
' <<EOF
EOF
