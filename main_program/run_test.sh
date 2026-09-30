#!/bin/bash
source venv/bin/activate
python gui_test.py &
sleep 2
pkill -f "python gui_test.py"
