#!/usr/bin/env python3
import can
from can import BitTiming, BitTimingFd
import time

# Configuration for the SLCAN device
device = 'COM13'
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
data = [i for i in range(1, 65)] # 64 byte data.

# Create a Standard CAN FD data frame
canfd_message = can.Message(
	arbitration_id=can_id,
	data=data,
	is_fd=True,
	is_extended_id=False,
)

## Create a CANFD Flexible Data Frame
canfd_flexible_message = can.Message(
	arbitration_id=can_id,
	data=data,
	is_fd=True,
	bitrate_switch=True,
	is_extended_id=False,
)
message = canfd_message

count = 1
try:
    while True:
        # Send the CAN message
        bus.send(message)
        print(f"counts:{count} Sent: {message}")
        count += 1

        # Wait for a second before sending the next message
        time.sleep(1)
       

except KeyboardInterrupt:
    print("Stopped by user")
    bus.shutdown()

except can.CanError as e:
    print(f"CAN error: {e}")
    bus.shutdown()
