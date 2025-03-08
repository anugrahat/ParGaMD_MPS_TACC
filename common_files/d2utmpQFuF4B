#!/bin/bash
#SBATCH --job-name=gamd_run
#SBATCH --account=ahnlab
#SBATCH --partition=gpu-ahn
#SBATCH --nodes=1
#SBATCH --cpus-per-task=5
#SBATCH --gres=gpu:1
#SBATCH --time=120:00:00



source ~/.bashrc
module load conda3/4.X cuda/11.8.0 
source activate openmm_env



# Navigate to the directory containing the input files
#cd /home/anugraha/pargamd_openmm/ParGaMD/common_files/       # Run your simulation

python gamdRunner -p CUDA   xml input.xml 
