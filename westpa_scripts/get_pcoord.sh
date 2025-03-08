#!/bin/bash
##############################################################################
# Example MDAnalysis-based driver script for WESTPA to compute:
#   - RMSD of CA atoms (mass-weighted, best-fit alignment)
#   - Radius of gyration of CA atoms (mass-weighted)
#
# Assumptions/Requirements:
#   1) In each segment directory ($WEST_CURRENT_SEG_DATA_REF), you have:
#        output_restart.dcd  -> The trajectory frames for that segment
#   2) The absolute paths below for chignolin.parm7 and chignolin.pdb
#      are valid on your HPC system.
#   3) MDAnalysis is available in your Python environment.
#
# WESTPA Environment Variables:
#   - $WEST_CURRENT_SEG_DATA_REF : Path to this segment's directory
#   - $WEST_PCOORD_RETURN        : Where to write RMSD/Rg data
#   - $SEG_DEBUG (optional)      : If set, script prints debug info
##############################################################################

# 1. Optionally enable debugging
if [ -n "$SEG_DEBUG" ]; then
    set -x
    env | sort
fi

# 2. Move to the segment directory
cd "$WEST_STRUCT_DATA_REF" || {
    echo "Error: Could not cd to \$WEST_CURRENT_SEG_DATA_REF=$WEST_STRUCT_DATA_REF" >&2
    exit 1
}

# 3. Create temp files for RMSD and Rg data
RMSD_FILE=$(mktemp --tmpdir rmsd_XXXX.xvg)
RG_FILE=$(mktemp --tmpdir rg_XXXX.xvg)

# 4. Create a small Python script to run MDAnalysis
cat << EOF > mdanalysis_rmsd_rg.py
#!/usr/bin/env python

import MDAnalysis as mda
import numpy as np
from MDAnalysis.analysis import rms

# Absolute paths to your HPC reference/topology files:
topology = "/home/anugraha/openmm_GaMD_anu_psc/ParGaMD_chig_2/common_files/chignolin.parm7"
ref_pdb  = "/home/anugraha/openmm_GaMD_anu_psc/ParGaMD_chig_2/common_files/chignolin.pdb"

# Trajectory is local to this segment directory
trajectory = "output_restart.dcd"

# Load the reference and the simulation trajectory
ref = mda.Universe(ref_pdb)
u   = mda.Universe(topology, trajectory)

# Select CA atoms
ref_ca    = ref.select_atoms("name CA")
mobile_ca = u.select_atoms("name CA")

# Prepare lists for RMSD and Rg
rmsd_values = []
rg_values   = []

# Loop through frames in the trajectory
for ts in u.trajectory:
    # -- Mass-weighted best-fit RMSD of CA to the reference CA --
    this_rmsd = rms.rmsd(
        mobile_ca.positions,
        ref_ca.positions,
        center=True,
        superposition=True,
        weights=mobile_ca.masses
    )

    # -- Mass-weighted Rg calculation for CA atoms --
    coords = mobile_ca.positions
    masses = mobile_ca.masses
    com    = np.average(coords, axis=0, weights=masses)
    sq_dist = np.sum((coords - com)**2, axis=1)
    this_rg = np.sqrt(np.average(sq_dist, weights=masses))

    rmsd_values.append(this_rmsd)
    rg_values.append(this_rg)

# Write out data in a simple two-column format (frame vs. value):
with open("${RMSD_FILE}", "w") as f_rms:
    f_rms.write("# frame RMSD(Angstrom)\n")
    for i, val in enumerate(rmsd_values):
        # Frame index i+1 for readability
        f_rms.write(f"{i+1} {val}\n")

with open("${RG_FILE}", "w") as f_rg:
    f_rg.write("# frame Rg(Angstrom)\n")
    for i, val in enumerate(rg_values):
        f_rg.write(f"{i+1} {val}\n")
EOF

chmod +x mdanalysis_rmsd_rg.py

# 5. Run the Python script
if ! ./mdanalysis_rmsd_rg.py; then
    echo "Error: MDAnalysis script execution failed!" >&2
    rm -f "$RMSD_FILE" "$RG_FILE" mdanalysis_rmsd_rg.py
    exit 1
fi

# 6. Extract RMSD and Rg columns, then write them to $WEST_PCOORD_RETURN
paste <(awk 'NR>1 {print $2}' "$RMSD_FILE") \
      <(awk 'NR>1 {print $2}' "$RG_FILE") \
      > "$WEST_PCOORD_RETURN"

# 7. (Optional) Show a quick preview if in debug mode
if [ -n "$SEG_DEBUG" ]; then
    echo "Preview of \$WEST_PCOORD_RETURN:"
    head -v "$WEST_PCOORD_RETURN"
    echo "Number of lines in \$WEST_PCOORD_RETURN: \$(wc -l < "$WEST_PCOORD_RETURN")"
fi

# 8. Clean up
rm -f "$RMSD_FILE" "$RG_FILE" mdanalysis_rmsd_rg.py
exit 0
