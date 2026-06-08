#!/bin/bash

cd $(dirname $0)  # script is in app/bin/ dir
cd ../..

uv run --no-sync python -m app.escalation_queue.manage_reader
