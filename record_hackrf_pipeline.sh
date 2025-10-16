#!/bin/bash
# Usage: ./record_hackrf_pipeline.sh <frequency> <squelch_threshold> <output_prefix> [rx_sn]

FREQ="$1"
SQUELCH="$2"
OUTPREFIX="$3"
RXSN="$4"

if [ -z "$RXSN" ]; then
    sudo hackrf_transfer -r - -f "$FREQ" -s 2000000 \
    | rtl_fm -M fm -s 2.4m -f 48k -r 48k -l "$SQUELCH" - \
    | sox -t raw -r 48k -e signed -b 16 -c 1 - "${OUTPREFIX}_%1n.wav" silence 1 0.1 1% 1 1.0 1% : newfile : restart
else
    sudo hackrf_transfer -r - -f "$FREQ" -s 2000000 -d "$RXSN" \
    | rtl_fm -M fm -s 2.4m -f 48k -r 48k -l "$SQUELCH" - \
    | sox -t raw -r 48k -e signed -b 16 -c 1 - "${OUTPREFIX}_%1n.wav" silence 1 0.1 1% 1 1.0 1% : newfile : restart
fi
