#!/usr/bin/env python

"""
This module tests cyclic send tasks.
"""

import gc
import sys
import time
import traceback
import unittest
from threading import Thread
from time import sleep
from typing import List
from unittest.mock import MagicMock

import can

from .config import *
from .message_helper import ComparingMessagesTestCase


class SimpleCyclicSendTaskTest(unittest.TestCase, ComparingMessagesTestCase):
    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        ComparingMessagesTestCase.__init__(
            self, allowed_timestamp_delta=0.016, preserves_channel=True
        )

    @unittest.skipIf(
        IS_CI,
        "the timing sensitive behaviour cannot be reproduced reliably on a CI server",
    )
    def test_cycle_time(self):
        msg = can.Message(
            is_extended_id=False, arbitration_id=0x123, data=[0, 1, 2, 3, 4, 5, 6, 7]
        )

        with can.interface.Bus(interface="virtual") as bus1:
            with can.interface.Bus(interface="virtual") as bus2:
                # disabling the garbage collector makes the time readings more reliable
                gc.disable()

                task = bus1.send_periodic(msg, 0.01, 1)
                self.assertIsInstance(task, can.broadcastmanager.CyclicSendTaskABC)

                sleep(2)
                size = bus2.queue.qsize()
                # About 100 messages should have been transmitted
                self.assertTrue(
                    80 <= size <= 120,
                    "100 +/- 20 messages should have been transmitted. But queue contained {}".format(
                        size
                    ),
                )
                last_msg = bus2.recv()
                next_last_msg = bus2.recv()

                # we need to reenable the garbage collector again
                gc.enable()

                # Check consecutive messages are spaced properly in time and have
                # the same id/data
                self.assertMessageEqual(last_msg, next_last_msg)

                # Check the message id/data sent is the same as message received
                # Set timestamp and channel to match recv'd because we don't care
                # and they are not initialized by the can.Message constructor.
                msg.timestamp = last_msg.timestamp
                msg.channel = last_msg.channel
                self.assertMessageEqual(msg, last_msg)

    def test_removing_bus_tasks(self):
        bus = can.interface.Bus(interface="virtual")
        tasks = []
        for task_i in range(10):
            msg = can.Message(
                is_extended_id=False,
                arbitration_id=0x123,
                data=[0, 1, 2, 3, 4, 5, 6, 7],
            )
            msg.arbitration_id = task_i
            task = bus.send_periodic(msg, 0.1, 1)
            tasks.append(task)
            self.assertIsInstance(task, can.broadcastmanager.CyclicSendTaskABC)

        assert len(bus._periodic_tasks) == 10

        for task in tasks:
            # Note calling task.stop will remove the task from the Bus's internal task management list
            task.stop()

        self.join_threads([task.thread for task in tasks], 5.0)

        assert len(bus._periodic_tasks) == 0
        bus.shutdown()

    def test_managed_tasks(self):
        bus = can.interface.Bus(interface="virtual", receive_own_messages=True)
        tasks = []
        for task_i in range(3):
            msg = can.Message(
                is_extended_id=False,
                arbitration_id=0x123,
                data=[0, 1, 2, 3, 4, 5, 6, 7],
            )
            msg.arbitration_id = task_i
            task = bus.send_periodic(msg, 0.1, 10, store_task=False)
            tasks.append(task)
            self.assertIsInstance(task, can.broadcastmanager.CyclicSendTaskABC)

        assert len(bus._periodic_tasks) == 0

        # Self managed tasks should still be sending messages
        for _ in range(50):
            received_msg = bus.recv(timeout=5.0)
            assert received_msg is not None
            assert received_msg.arbitration_id in {0, 1, 2}

        for task in tasks:
            task.stop()

        self.join_threads([task.thread for task in tasks], 5.0)

        bus.shutdown()

    def test_stopping_perodic_tasks(self):
        bus = can.interface.Bus(interface="virtual")
        tasks = []
        for task_i in range(10):
            msg = can.Message(
                is_extended_id=False,
                arbitration_id=0x123,
                data=[0, 1, 2, 3, 4, 5, 6, 7],
            )
            msg.arbitration_id = task_i
            task = bus.send_periodic(msg, 0.1, 1)
            tasks.append(task)

        assert len(bus._periodic_tasks) == 10
        # stop half the tasks using the task object
        for task in tasks[::2]:
            task.stop()

        assert len(bus._periodic_tasks) == 5

        # stop the other half using the bus api
        bus.stop_all_periodic_tasks(remove_tasks=False)
        self.join_threads([task.thread for task in tasks], 5.0)

        # Tasks stopped via `stop_all_periodic_tasks` with remove_tasks=False should
        # still be associated with the bus (e.g. for restarting)
        assert len(bus._periodic_tasks) == 5

        bus.shutdown()

    def test_restart_perodic_tasks(self):
        period = 0.01
        safe_timeout = period * 5 if not IS_PYPY else 1.0
        duration = 0.3

        msg = can.Message(
            is_extended_id=False, arbitration_id=0x123, data=[0, 1, 2, 3, 4, 5, 6, 7]
        )

        def _read_all_messages(_bus: "can.interfaces.virtual.VirtualBus") -> None:
            sleep(safe_timeout)
            while not _bus.queue.empty():
                _bus.recv(timeout=period)
            sleep(safe_timeout)

        with can.ThreadSafeBus(interface="virtual", receive_own_messages=True) as bus:
            task = bus.send_periodic(msg, period)
            self.assertIsInstance(task, can.broadcastmanager.ThreadBasedCyclicSendTask)

            # Test that the task is sending messages
            sleep(safe_timeout)
            assert not bus.queue.empty(), "messages should have been transmitted"

            # Stop the task and check that messages are no longer being sent
            bus.stop_all_periodic_tasks(remove_tasks=False)
            _read_all_messages(bus)
            assert bus.queue.empty(), "messages should not have been transmitted"

            # Restart the task and check that messages are being sent again
            task.start()
            sleep(safe_timeout)
            assert not bus.queue.empty(), "messages should have been transmitted"

            # Stop the task and check that messages are no longer being sent
            bus.stop_all_periodic_tasks(remove_tasks=False)
            _read_all_messages(bus)
            assert bus.queue.empty(), "messages should not have been transmitted"

            # Restart the task with limited duration and wait until it stops
            task.duration = duration
            task.start()
            sleep(duration + safe_timeout)
            assert task.stopped
            assert time.time() > task.end_time
            assert not bus.queue.empty(), "messages should have been transmitted"
            _read_all_messages(bus)
            assert bus.queue.empty(), "messages should not have been transmitted"

            # Restart the task and check that messages are being sent again
            task.start()
            sleep(safe_timeout)
            assert not bus.queue.empty(), "messages should have been transmitted"

            # Stop all tasks and wait for the thread to exit
            bus.stop_all_periodic_tasks()
            # Avoids issues where the thread is still running when the bus is shutdown
            self.join_threads([task.thread], 5.0)

    @unittest.skipIf(IS_CI, "fails randomly when run on CI server")
    def test_thread_based_cyclic_send_task(self):
        bus = can.ThreadSafeBus(interface="virtual")
        msg = can.Message(
            is_extended_id=False, arbitration_id=0x123, data=[0, 1, 2, 3, 4, 5, 6, 7]
        )

        # good case, bus is up
        on_error_mock = MagicMock(return_value=False)
        task = can.broadcastmanager.ThreadBasedCyclicSendTask(
            bus=bus,
            lock=bus._lock_send_periodic,
            messages=msg,
            period=0.1,
            duration=3,
            on_error=on_error_mock,
        )
        sleep(1)
        on_error_mock.assert_not_called()
        task.stop()
        bus.shutdown()

        # bus has been shut down
        on_error_mock = MagicMock(return_value=False)
        task = can.broadcastmanager.ThreadBasedCyclicSendTask(
            bus=bus,
            lock=bus._lock_send_periodic,
            messages=msg,
            period=0.1,
            duration=3,
            on_error=on_error_mock,
        )
        sleep(1)
        self.assertEqual(1, on_error_mock.call_count)
        task.stop()

        # bus is still shut down, but on_error returns True
        on_error_mock = MagicMock(return_value=True)
        task = can.broadcastmanager.ThreadBasedCyclicSendTask(
            bus=bus,
            lock=bus._lock_send_periodic,
            messages=msg,
            period=0.1,
            duration=3,
            on_error=on_error_mock,
        )
        sleep(1)
        self.assertTrue(on_error_mock.call_count > 1)
        task.stop()

    def test_modifier_callback(self) -> None:
        msg_list: List[can.Message] = []

        def increment_first_byte(msg: can.Message) -> None:
            msg.data[0] = (msg.data[0] + 1) % 256

        original_msg = can.Message(
            is_extended_id=False, arbitration_id=0x123, data=[0] * 8
        )

        with can.ThreadSafeBus(interface="virtual", receive_own_messages=True) as bus:
            notifier = can.Notifier(bus=bus, listeners=[msg_list.append])
            task = bus.send_periodic(
                msgs=original_msg, period=0.001, modifier_callback=increment_first_byte
            )
            time.sleep(0.2)
            task.stop()
            notifier.stop()

        self.assertEqual(b"\x01\x00\x00\x00\x00\x00\x00\x00", bytes(msg_list[0].data))
        self.assertEqual(b"\x02\x00\x00\x00\x00\x00\x00\x00", bytes(msg_list[1].data))
        self.assertEqual(b"\x03\x00\x00\x00\x00\x00\x00\x00", bytes(msg_list[2].data))
        self.assertEqual(b"\x04\x00\x00\x00\x00\x00\x00\x00", bytes(msg_list[3].data))
        self.assertEqual(b"\x05\x00\x00\x00\x00\x00\x00\x00", bytes(msg_list[4].data))
        self.assertEqual(b"\x06\x00\x00\x00\x00\x00\x00\x00", bytes(msg_list[5].data))
        self.assertEqual(b"\x07\x00\x00\x00\x00\x00\x00\x00", bytes(msg_list[6].data))

    @staticmethod
    def join_threads(threads: List[Thread], timeout: float) -> None:
        stuck_threads: List[Thread] = []
        t0 = time.perf_counter()
        for thread in threads:
            time_left = timeout - (time.perf_counter() - t0)
            if time_left > 0.0:
                thread.join(time_left)
            if thread.is_alive():
                if platform.python_implementation() == "CPython":
                    # print thread frame to help with debugging
                    frame = sys._current_frames()[thread.ident]
                    traceback.print_stack(frame, file=sys.stderr)
                stuck_threads.append(thread)
        if stuck_threads:
            err_message = (
                f"Threads did not stop within {timeout:.1f} seconds: "
                f"[{', '.join([str(t) for t in stuck_threads])}]"
            )
            raise RuntimeError(err_message)


if __name__ == "__main__":
    unittest.main()
