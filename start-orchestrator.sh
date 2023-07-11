#!/bin/bash

DEV_INIT_MODE=${1:-0}
EXPERIMENT_PROTOCOL=${2:-"tcp"}

cd /home/tiritor/working_space/orchestrator/ 
source .venv/bin/activate

export SDE="/home/netlabadmin/BF/bf-sde-9.7.0" 
export SDE_INSTALL="/home/netlabadmin/BF/bf-sde-9.7.0/install"

python3 orchestrator.py --dev-init-mode $DEV_INIT_MODE --experiment-protocol $EXPERIMENT_PROTOCOL 2>&1 > orchestrator-$DATE.log 
