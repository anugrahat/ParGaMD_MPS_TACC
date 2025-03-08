#!/bin/bash



source ~/.bashrc
module load conda3/4.X cuda/11.8.0 
source activate openmm_env





#export PATH=$PATH:$HOME/bin
#export LD_LIBRARY_PATH=$LD_LIBRARY_PATH
#export PATH="$PATH:/home/anugraha/pargamd_openmm/ParGaMD/common_files/gamd-openmm/"

# Define simulation root
if [[ -z "$WEST_SIM_ROOT" ]]; then
    export WEST_SIM_ROOT="$PWD"
fi
export SIM_NAME=$(basename $WEST_SIM_ROOT)
echo "simulation $SIM_NAME root is $WEST_SIM_ROOT"

# Source Amber environment
# source $AMBERHOME/amber.sh

# Set runtime variables
#export NODELOC=/home/anugraha/pargamd_openmm/ParGaMD/
export USE_LOCAL_SCRATCH=1
export WM_ZMQ_MASTER_HEARTBEAT=100
export WM_ZMQ_WORKER_HEARTBEAT=100
export WM_ZMQ_TIMEOUT_FACTOR=300

# Set Amber executables
# export PMEMD=$AMBERHOME/bin/pmemd.cuda
# export CPPTRAJ=$AMBERHOME/bin/cpptraj
