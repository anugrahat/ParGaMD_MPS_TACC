#!/bin/bash
#SBATCH -J mps_gpu_job          # Job name
#SBATCH -o job.out 
#SBATCH -e job.err                                # Output filename (%j = job ID)
#SBATCH -t 01:00:00              # Wall time (1 hour)
#SBATCH -N 1                     # Number of nodes                    
#SBATCH --cpus-per-task=32        # CPUs per task             # Request 1 GPU
#SBATCH -p gh                    # GPU partition (modify if needed)
#SBATCH -A MCB23037                    # Project/Allocation name




##############################################################################
# 0) Basic environment and module loads
##############################################################################
set -x
cd "$SLURM_SUBMIT_DIR"

source ~/.bashrc
#module load gcc/14.2.0
module load cuda/12.6
conda init
conda  activate openmm_westpa

export WEST_SIM_ROOT="$SLURM_SUBMIT_DIR"
cd "$WEST_SIM_ROOT"

# Example concurrency variables
export OPENMM_CPU_THREADS=2
export OMP_NUM_THREADS=1

#echo "Initially, CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES"
#nvidia-smi -L

##############################################################################
# 1) (Optional) Start MPS
##############################################################################

export CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
export CUDA_MPS_LOG_DIRECTORY=/tmp/nvidia-log

echo "Starting MPS daemon..."

export TACC_TASKS_PER_NODE=1 

ibrun -np $SLURM_NNODES nvidia-cuda-mps-control -d
unset TACC_TASKS_PER_NODE
#nvidia-cuda-mps-control -d

sleep 5


ibrun -np $SLURM_NNODES bash -c 'ps aux | grep "[n]vidia-cuda-mps-control"'
echo "set_active_thread_percentage 40" | nvidia-cuda-mps-control


#if pgrep -f  "nvidia-cuda-mps-control" > /dev/null; then
   # echo "set_active_thread_percentage 40" | nvidia-cuda-mps-control
#else
   # echo "ERROR: MPS did not start properly!"
    #exit 1
#fi


#echo set_active_thread_percentage 40 | nvidia-cuda-mps-control



nvidia-smi -L

echo "CUDA_VISIBLE_DEVICES before setting: $CUDA_VISIBLE_DEVICES"



if [ -z "$CUDA_VISIBLE_DEVICES" ]; then
    CUDA_VISIBLE_DEVICES=$(nvidia-smi --query-gpu=index --format=csv,noheader | tr '\n' ',')
    export CUDA_VISIBLE_DEVICES
    echo "Manually setting CUDA_VISIBLE_DEVICES: $CUDA_VISIBLE_DEVICES"
fi
##############################################################################
# 2) Initialize WESTPA
##############################################################################
./init.sh
echo "init.sh ran"
source env.sh || exit 1
export SERVER_INFO="${WEST_SIM_ROOT}/west_zmq_info.json"

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
# 4A) sm% logger (nvidia-smi dmon)
SM_LOG="gpu_dmon_${SLURM_JOB_ID}.log"
echo "Logging SM usage to $SM_LOG (every 10s)"
nvidia-smi dmon -s u -d 10 > "$SM_LOG" &
DMON_PID=$!

# 4B) memory usage & overall GPU util
MEM_LOG="gpu_query_${SLURM_JOB_ID}.log"
echo "Logging memory/overall usage to $MEM_LOG (every 10s)"
nvidia-smi --query-gpu=timestamp,index,name,utilization.gpu,utilization.memory,memory.total,memory.used \
           --format=csv -l 10 > "$MEM_LOG" &
QPID=$!

##############################################################################
# 5) Launch GPU workers
##############################################################################
export WORKERS_PER_GPU=8
IFS=',' read -ra DEVICES <<< "$CUDA_VISIBLE_DEVICES"
total_workers=$(( ${#DEVICES[@]} * WORKERS_PER_GPU ))

echo "Debug: CUDA_VISIBLE_DEVICES = $CUDA_VISIBLE_DEVICES"
echo "Debug: DEVICES = ${DEVICES[@]}"
echo "Debug: total_workers = $total_workers"


if [ ${#DEVICES[@]} -eq 0 ]; then
    echo "ERROR: No GPUs detected! Exiting..."
    exit 1
fi



for gpuid in "${DEVICES[@]}"; do
    for ((w=1; w<=WORKERS_PER_GPU; w++)); do
        (
          export CUDA_VISIBLE_DEVICES="$gpuid"
	  echo "Launching worker $w on GPU $gpuid..."
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
