#!/bin/bash

cd $(dirname $0)  # script is in app/bin/ dir
cd ../..

poetry run python -m app.escalation_queue_reader.escalation_queue_reader
``