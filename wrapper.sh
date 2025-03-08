#!/bin/bash
module load cuda/11.8.0
nsys profile --trace=cuda \
    --stats=true \
    --force-overwrite true \
    -o my_profile_no_mps \
    bash -c './run_WE_multi_no_mps.sh'
