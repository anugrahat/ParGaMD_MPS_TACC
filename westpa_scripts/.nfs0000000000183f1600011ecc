#!/bin/bash
set -x  # Print commands for debugging

##############################################################################
# 1) Rely on HPC to set CUDA_VISIBLE_DEVICES
##############################################################################
# echo "[DEBUG] HPC provided CUDA_VISIBLE_DEVICES = $CUDA_VISIBLE_DEVICES"
# nvidia-smi

##############################################################################
# 2) Create and move into the simulation directory
##############################################################################
mkdir -pv "$WEST_CURRENT_SEG_DATA_REF"
cd "$WEST_CURRENT_SEG_DATA_REF" || exit 1

##############################################################################
# 3) Link necessary files (topology, coords, XML)
##############################################################################
ln -sfv "$WEST_SIM_ROOT/common_files/chignolin.parm7" .
ln -sfv "$WEST_SIM_ROOT/common_files/gamd-restart.dat" .
ln -sfv "$WEST_SIM_ROOT/common_files/input.xml" .
ln -sfv "$WEST_SIM_ROOT/common_files/chignolin.rst7" .

# Fix XML output directory to current location
sed -i 's|<directory>.*</directory>|<directory>.</directory>|' input.xml

##############################################################################
# 4) Handle GaMD checkpoint for first vs. subsequent iteration
##############################################################################
if [ "$WEST_CURRENT_ITER" -eq 1 ]; then
    rsync -av --progress --checksum  /home/anugraha/openmm_GaMD_anu_psc/ParGaMD_chig_2/common_files/out27/gamd_restart.checkpoint ./gamd_restart.checkpoint
    sync
    python /home/anugraha/openmm_GaMD_anu_psc/ParGaMD_chig_2/common_files/gamdRunner -p CUDA -r xml input.xml
else
    cp -L "$WEST_PARENT_DATA_REF/gamd_restart.checkpoint" ./gamd_restart.checkpoint
    python /home/anugraha/openmm_GaMD_anu_psc/ParGaMD_chig_2/common_files/gamdRunner -p CUDA -r xml input.xml
fi


if [ ! -f "gamd_restart.checkpoint" ] || [ ! -f "output_restart.dcd" ]; then
    echo "Error: GaMD simulation failed to generate output files"
    ls -lh
    exit 1
fi

##############################################################################
# 6) Post-processing with MDAnalysis: compute RMSD and Rg
##############################################################################
RMSD_FILE="rmsd_ca.xvg"
RG_FILE="rg_ca.xvg"

# Create a Python script on-the-fly to run MDAnalysis
cat << EOF > mdanalysis_rmsd_rg.py
#!/usr/bin/env python

import MDAnalysis as mda
from MDAnalysis.analysis import rms
import numpy as np

# Load the system
u = mda.Universe("chignolin.parm7", "output_restart.dcd")
# Load reference (ensure it has matching CA atoms in same order)
ref = mda.Universe("${WEST_SIM_ROOT}/common_files/chignolin.pdb")

# Select only CA atoms
mobile_ca = u.select_atoms("name CA")
ref_ca    = ref.select_atoms("name CA")

rmsd_list = []
rg_list   = []

for ts in u.trajectory:
    # mass-weighted best-fit RMSD
    # 'weights=mobile_ca.masses' ensures mass weighting
    # center=True and superposition=True => do best-fit alignment
    rmsd_value = rms.rmsd(
        mobile_ca.positions,
        ref_ca.positions,
        center=True,
        superposition=True,
        weights=mobile_ca.masses
    )
    # Radius of gyration (all CA positions)
    rg_value = mobile_ca.radius_of_gyration()
    rmsd_list.append(rmsd_value)
    rg_list.append(rg_value)

# Write out data in a format similar to cpptraj .xvg
with open("${RMSD_FILE}", "w") as f:
    f.write("# frame RMSD_CA(Angstrom)\n")
    for i, val in enumerate(rmsd_list):
        f.write(f"{i} {val}\n")

with open("${RG_FILE}", "w") as f:
    f.write("# frame Rg_CA(Angstrom)\n")
    for i, val in enumerate(rg_list):
        f.write(f"{i} {val}\n")
EOF

# Run the Python script
python mdanalysis_rmsd_rg.py
if [ $? -ne 0 ]; then
    echo "Error: MDAnalysis RMSD/Rg calculation failed."
    exit 1
fi

##############################################################################
# 7) Write final RMSD and Rg data to $WEST_PCOORD_RETURN
##############################################################################
if [ -f "$RMSD_FILE" ] && [ -f "$RG_FILE" ]; then
    > "$WEST_PCOORD_RETURN"
    # Extract second column from lines >1 of each file, then paste them
    paste <(awk 'NR>1 {print $2}' "$RMSD_FILE") \
          <(awk 'NR>1 {print $2}' "$RG_FILE") >> "$WEST_PCOORD_RETURN"
else
    echo "Error: Missing $RMSD_FILE or $RG_FILE"
    exit 1
fi

##############################################################################
# 8) Optional debugging
##############################################################################
#if [ -n "\$SEG_DEBUG" ]; then
#    echo "Preview of $WEST_PCOORD_RETURN:"
#    head -v "$WEST_PCOORD_RETURN"
#fi

echo "Segment run completed successfully."
exit 0
