#!/usr/bin/env python3
import can
import time
from can import BitTiming, BitTimingFd

# Configuration for the SLCAN device
device = 'COM14'
# for standard CAN
#baud_rate = 500000  # Set the appropriate baud rate for your setup
# for CANFD timing ; nom bitrate = 1M, data bitrate = 5M 
timing_fd = BitTimingFd(
    f_clock=60_000_000,
	nom_brp=1,
	nom_tseg1=44,
	nom_tseg2=15,
	nom_sjw=1,
	data_brp=1,
	data_tseg1=8,
	data_tseg2=3,
	data_sjw=1,
)

# Create a CAN bus instance using the SLCAN interface
bus = can.Bus(interface='slcan', channel=device, timing=timing_fd)

# Define a simple CAN message
can_id = 0x123  # CAN ID
count = 1
# Create a CAN message

try:
    while True:
        # Send the CAN message
    
        message = bus.recv()
        print(f"counts:{count} rece: {message}")
        count += 1

except KeyboardInterrupt:
    print("Stopped by user")
    bus.shutdown()

except can.CanError as e:
    print(f"CAN error: {e}")
    bus.shutdown()
