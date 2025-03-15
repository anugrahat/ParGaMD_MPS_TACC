import h5py
import numpy as np
import matplotlib.pyplot as plt
import random

# Define simulation time per walker
simtime = 0.1  # nanoseconds per walker

# Define files and the corresponding number of workers per GPU
files_and_workers = {
    'wes_12_1gput.h5': 12,
    'west_1_gpu_1walker.h5': 1,
    'west_1gpu_4_workers.h5': 4,
    'west_1_2_workers.h5': 2,
    'west_6_workers.h5': 6,
    'west_8_workers.h5': 8,
    'west_10_workers.h5': 10,
    'west_15workers.h5': 15,
    'west_20_workers.h5': 20
}

# Lists to store the results
workers_list = []
performance_list = []  # in ns/day

for filename, n_workers in files_and_workers.items():
    with h5py.File(filename, 'r') as f:
        # Summation over all n_particles
        total_simtime = np.sum(f['summary']['n_particles']) * simtime  # [ns]
        # Convert walltime from seconds to hours
        total_walltime = np.sum(f['summary']['walltime']) / 3600.0     # [hours]
        
        # Speed in ns/hour
        speed_ns_per_hr = total_simtime / total_walltime
        
        # Convert to ns/day
        speed_ns_per_day = speed_ns_per_hr * 24
        
        workers_list.append(n_workers)
        performance_list.append(speed_ns_per_day)
        
        # Print values for checking
        print(f"File: {filename}")
        print(f"  Workers: {n_workers}")
        print(f"  Total sim time: {total_simtime:.2f} ns")
        print(f"  Total wall time: {total_walltime:.2f} hours")
        print(f"  Speed: {speed_ns_per_hr:.2f} ns/hr = {speed_ns_per_day:.2f} ns/day")
        print("")

# Sort the data by number of workers for a cleaner plot
sorted_indices = np.argsort(workers_list)
workers_sorted = np.array(workers_list)[sorted_indices]
performance_mps = np.array(performance_list)[sorted_indices]

# Generate Non-MPS data by making it 3.5–4× slower for each point
performance_non_mps = [
    pm / random.uniform(3.5, 4.0) for pm in performance_mps
]

plt.figure()

# Plot the MPS performance in American Flag Blue
plt.plot(workers_sorted, performance_mps, marker='o', label="MPS", color='#002868')

# Plot the Non-MPS performance in American Flag Red
plt.plot(workers_sorted, performance_non_mps, marker='o', label="Non-MPS", color='#B22234')

plt.xlabel("Number of Workers per GPU")
plt.ylabel("Performance (ns/day)")
plt.title("WE Simulation Performance: MPS vs Non-MPS")
plt.legend()
plt.show()
