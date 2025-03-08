#!/bin/bash

#SBATCH --job-name=gamd_run             # Job name
#SBATCH --account=ahnlab               # Account name
#SBATCH --partition=gpu-ahn            # Partition name
#SBATCH --nodes=1                      # Number of nodes
#SBATCH --ntasks-per-node=1            # Number of tasks per node
#SBATCH --cpus-per-task=64             # Number of CPU cores per task
#SBATCH --gres=gpu:1                   # Request 1 GPU
#SBATCH --time=120:00:00               # Time limit hrs:min:sec
#SBATCH --mail-type=BEGIN,END          # Email notifications
#SBATCH --mail-user=anuthyagatur@ucdavis.edu # Email address

module load conda3/4.X
module load cuda/11.8.0
source activate openmm_env  # Activate your environment

export PATH="$PATH:/home/anugraha/pargamd_openmm/ParGaMD/common_files/gamd-openmm/"

# Navigate to the directory containing the input files
#cd /home/anugraha/pargamd_openmm/ParGaMD/common_files/       # Run your simulation

python /home/anugraha/pargamd_openmm/ParGaMD/common_files/gamd-openmm/gamdRunner  xml input.xml 