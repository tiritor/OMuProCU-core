#!/bin/bash

export SDE="/home/netlabadmin/BF/bf-sde-9.7.0" 
export SDE_INSTALL="/home/netlabadmin/BF/bf-sde-9.7.0/install"
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

DEV_INIT_MODE=${1:-0}
EXPERIMENT_PROTOCOL=${2:-"tcp"}

EDGE_DEVICES=("stordis-01" "stordis-03")
CENTER_DEVICES=("stordis-02" "stordis-04")

if [[ " ${EDGE_DEVICES[*]} " =~ " `hostname` " ]]; then
    sudo tmux kill-session -t sal 2> /dev/null
    sudo tmux kill-session -t asd 2> /dev/null
    cd /home/netlabadmin/ && ./start-switch_background.sh
    echo "Waiting until dashboard is started. (15 secs)" 
    sleep 15
elif [[ " ${CENTER_DEVICES[*]} " =~ " `hostname` " ]]; then
    echo ""
else
echo "ERROR! Device `hostname` is not part in one of both available categories!"
exit 1
fi

cd /home/tiritor/working_space/orchestrator/ 
source .venv/bin/activate


python3 orchestrator.py --dev-init-mode $DEV_INIT_MODE --experiment-protocol $EXPERIMENT_PROTOCOL 2>&1 > orchestrator-$DATE.log 
