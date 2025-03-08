#!/bin/bash
#SBATCH --job-name="chignolin_run"
#SBATCH --output="job.out"
#SBATCH -p GPU-shared
#SBATCH -N 1
#SBATCH --gpus=h100-80:1
#SBATCH -t 04:00:00
set -x
cd $SLURM_SUBMIT_DIR
source ~/.bashrc



module load gcc/13.3.1-p20240614
module load openmpi/5.0.3-gcc13.2.1

module load cuda/12.4.0
module load anaconda3/2024.10-1

#module load amber/22
source activate openmm_env

export PATH=/home/anugraha/.conda/envs/openmm_env/bin:$PATH
export WEST_SIM_ROOT=$SLURM_SUBMIT_DIR
cd $WEST_SIM_ROOT

# Enable CUDA MPS
export CUDA_MPS_PIPE_DIRECTORY=/tmp/nvidia-mps
export CUDA_MPS_LOG_DIRECTORY=/tmp/nvidia-log
mkdir -p $CUDA_MPS_PIPE_DIRECTORY $CUDA_MPS_LOG_DIRECTORY
nvidia-cuda-mps-control -d

./init.sh || { echo "Error: init.sh failed"; exit 1; }
source env.sh || exit 1
env | sort
SERVER_INFO=$WEST_SIM_ROOT/west_zmq_info.json

num_gpu_per_node=1
workers_per_gpu=16  # Adjust based on memory/GPU capability
total_workers=$((num_gpu_per_node * workers_per_gpu))

# Generate nodefilelist.txt
rm -rf nodefilelist.txt
scontrol show hostname $SLURM_JOB_NODELIST > nodefilelist.txt

# Start the master process
w_run  --work-manager=zmq --n-workers=0 --zmq-mode=master --zmq-write-host-info=$SERVER_INFO --zmq-comm-mode=tcp &> west-$SLURM_JOBID-local.log &

# Wait for server to start
for ((n=0; n<60; n++)); do
    if [ -e $SERVER_INFO ]; then
        echo "== server info file $SERVER_INFO =="
        cat $SERVER_INFO
        break
    fi
    sleep 1
done

if ! [ -e $SERVER_INFO ]; then
    echo 'Error: Server failed to start'
    exit 1
fi

# Run the node.sh script locally on each node using srun
for node in $(cat nodefilelist.txt); do
    srun -N1 -n1 bash node.sh $SLURM_SUBMIT_DIR $SLURM_JOBID $node $CUDA_VISIBLE_DEVICES \
        --work-manager=zmq --n-workers=$total_workers --zmq-mode=client --zmq-read-host-info=$SERVER_INFO \
        --zmq-comm-mode=tcp &

    if [ $? -ne 0 ]; then
        echo "Error: srun failed on node $node"
        exit 1
    fi
done

wait

# Stop CUDA MPS
echo quit | nvidia-cuda-mps-control

echo "Weighted ensemble simulation completed successfully"
