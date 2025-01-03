"""
Interface for slcan compatible interfaces (win32/linux).
"""

import io
import logging
import time
import warnings
from typing import Any, Optional, Tuple, Union

from can import BitTiming, BitTimingFd, BusABC, CanProtocol, Message, typechecking
from can.exceptions import (
    CanInitializationError,
    CanInterfaceNotImplementedError,
    CanOperationError,
    error_check,
)
from can.util import check_or_adjust_timing_clock, deprecated_args_alias

logger = logging.getLogger(__name__)

try:
    import serial
except ImportError:
    logger.warning(
        "You won't be able to use the slcan can backend without "
        "the serial module installed!"
    )
    serial = None


class slcanBus(BusABC):
    """
    slcan interface
    """

    # the supported bitrates and their commands
    _BITRATES = {
        10000: "S0",
        20000: "S1",
        50000: "S2",
        100000: "S3",
        125000: "S4",
        250000: "S5",
        500000: "S6",
        750000: "S7",
        1000000: "S8",
        83300: "S9",
    }

    _SLEEP_AFTER_SERIAL_OPEN = 2  # in seconds

    _OK = b"\r"
    _ERROR = b"\a"

    LINE_TERMINATOR = b"\r"

    @deprecated_args_alias(
        deprecation_start="4.5.0",
        deprecation_end="5.0.0",
        ttyBaudrate="tty_baudrate",
    )
    def __init__(
        self,
        channel: typechecking.ChannelStr,
        tty_baudrate: int = 115200,
        bitrate: Optional[int] = None,
        timing: Optional[Union[BitTiming, BitTimingFd]] = None,
        sleep_after_open: float = _SLEEP_AFTER_SERIAL_OPEN,
        rtscts: bool = False,
        listen_only: bool = False,
        timeout: float = 0.001,
        **kwargs: Any,
    ) -> None:
        """
        :param str channel:
            port of underlying serial or usb device (e.g. ``/dev/ttyUSB0``, ``COM8``, ...)
            Must not be empty. Can also end with ``@115200`` (or similarly) to specify the baudrate.
        :param int tty_baudrate:
            baudrate of underlying serial or usb device (Ignored if set via the ``channel`` parameter)
        :param bitrate:
            Bitrate in bit/s
        :param timing:
            Optional :class:`~can.BitTiming` instance to use for custom bit timing setting.
            If this argument is set then it overrides the bitrate and btr arguments. The
            `f_clock` value of the timing instance must be set to 8_000_000 (8MHz)
            for standard CAN.
            CAN FD and the :class:`~can.BitTimingFd`.
        :param poll_interval:
            Poll interval in seconds when reading messages
        :param sleep_after_open:
            Time to wait in seconds after opening serial connection
        :param rtscts:
            turn hardware handshake (RTS/CTS) on and off
        :param listen_only:
            If True, open interface/channel in listen mode with ``L`` command.
            Otherwise, the (default) ``O`` command is still used. See ``open`` method.
        :param timeout:
            Timeout for the serial or usb device in seconds (default 0.001)

        :raise ValueError: if both ``bitrate`` and ``btr`` are set or the channel is invalid
        :raise CanInterfaceNotImplementedError: if the serial module is missing
        :raise CanInitializationError: if the underlying serial connection could not be established
        """
        self._listen_only = listen_only

        if serial is None:
            raise CanInterfaceNotImplementedError("The serial module is not installed")

        btr: Optional[str] = kwargs.get("btr", None)
        if btr is not None:
            warnings.warn(
                "The 'btr' argument is deprecated since python-can v4.5.0 "
                "and scheduled for removal in v5.0.0. "
                "Use the 'timing' argument instead.",
                DeprecationWarning,
                stacklevel=1,
            )

        if not channel:  # if None or empty
            raise ValueError("Must specify a serial port.")
        if "@" in channel:
            (channel, baudrate) = channel.split("@")
            tty_baudrate = int(baudrate)

        with error_check(exception_type=CanInitializationError):
            self.serialPortOrig = serial.serial_for_url(
                channel,
                baudrate=tty_baudrate,
                rtscts=rtscts,
                timeout=timeout,
            )

        self._buffer = bytearray()
        self._can_protocol = CanProtocol.CAN_20

        time.sleep(sleep_after_open)

        with error_check(exception_type=CanInitializationError):
            if isinstance(timing, BitTiming):
                timing = check_or_adjust_timing_clock(timing, valid_clocks=[8_000_000])
                self.set_bitrate_reg(f"{timing.btr0:02X}{timing.btr1:02X}")
            elif isinstance(timing, BitTimingFd):
                timing = check_or_adjust_timing_clock(timing, valid_clocks=[60_000_000])
                self._set_bit_timing_fd(timing)
            else:
                if bitrate is not None and btr is not None:
                    raise ValueError("Bitrate and btr mutually exclusive.")
                if bitrate is not None:
                    self.set_bitrate(bitrate)
                if btr is not None:
                    self.set_bitrate_reg(btr)
            self.open()

        super().__init__(channel, **kwargs)

    def _set_bit_timing_fd(self, timing: BitTimingFd) -> None:
        nomStr = f"P{timing.nom_sjw:04d}{timing.nom_tseg1:04d}{timing.nom_tseg2:04d}{timing.nom_brp:04d}"
        dataStr = f"p{timing.data_sjw:04d}{timing.data_tseg1:04d}{timing.data_tseg2:04d}{timing.data_brp:04d}"
		
        self.close()
        self._write(nomStr)
        self._write(dataStr)
        self.open()

    def set_bitrate(self, bitrate: int) -> None:
        """
        :param bitrate:
            Bitrate in bit/s

        :raise ValueError: if ``bitrate`` is not among the possible values
        """
        if bitrate in self._BITRATES:
            bitrate_code = self._BITRATES[bitrate]
        else:
            bitrates = ", ".join(str(k) for k in self._BITRATES.keys())
            raise ValueError(f"Invalid bitrate, choose one of {bitrates}.")

        self.close()
        self._write(bitrate_code)
        self.open()

    def set_bitrate_reg(self, btr: str) -> None:
        """
        :param btr:
            BTR register value to set custom can speed as a string `xxyy` where
            xx is the BTR0 value in hex and yy is the BTR1 value in hex.
        """
        self.close()
        self._write("s" + btr)
        self.open()

    def _write(self, string: str) -> None:
        with error_check("Could not write to serial device"):
            self.serialPortOrig.write(string.encode() + self.LINE_TERMINATOR)
            self.serialPortOrig.flush()

    def _read(self, timeout: Optional[float]) -> Optional[str]:
        _timeout = serial.Timeout(timeout)

        with error_check("Could not read from serial device"):
            while not _timeout.expired():
                ok_index = self._buffer.find(self._OK)
                error_index = self._buffer.find(self._ERROR)
                if error_index != -1 or ok_index != -1:
                    first_marker_index = (
                        min(idx for idx in [error_index, ok_index] if idx != -1)
                    )

                    string = self._buffer[: first_marker_index + 1].decode()
                    self._buffer = bytearray(self._buffer[first_marker_index + 1 :])
                    return string
                # Due to accessing `serialPortOrig.in_waiting` too often will reduce the performance.
                # We read the `serialPortOrig.in_waiting` only once here.
                in_waiting = self.serialPortOrig.in_waiting
                if in_waiting > 0:
                    new_bytes = self.serialPortOrig.read(size=in_waiting)
                    self._buffer.extend(new_bytes)
                else:
                    time.sleep(0.001)

        return None

    def flush(self) -> None:
        self._buffer.clear()
        with error_check("Could not flush"):
            self.serialPortOrig.reset_input_buffer()

    def open(self) -> None:
        if self._listen_only:
            self._write("L")
        else:
            self._write("O")

    def close(self) -> None:
        self._write("C")

    def decode_hex_dlc(self, hex_dlc: str) -> int:
        hex_dlc = hex_dlc.upper()
        if hex_dlc.isdigit():
            num = int(hex_dlc)
            if 0 <= num <= 8:
                return num
            elif num == 9:
                return 12
        elif hex_dlc == 'A':
            return 16
        elif hex_dlc == 'B':
            return 20
        elif hex_dlc == 'C':
            return 24
        elif hex_dlc == 'D':
            return 32
        elif hex_dlc == 'E':
            return 48
        return 64

    def _recv_internal(
        self, timeout: Optional[float]
    ) -> Tuple[Optional[Message], bool]:
        canId = None
        remote = False
        extended = False
        is_fd = False
        bitrate_switch = False
        data = None

        string = self._read(timeout)

        if not string:
            pass
        elif string[0] in (
            "T",
            "x",  # x is an alternative extended message identifier for CANDapter
        ):
            # extended frame
            canId = int(string[1:9], 16)
            dlc = int(string[9])
            extended = True
            data = bytearray.fromhex(string[10 : 10 + dlc * 2])
        elif string[0] == "t":
            # normal frame
            canId = int(string[1:4], 16)
            dlc = int(string[4])
            data = bytearray.fromhex(string[5 : 5 + dlc * 2])
        elif string[0] == "r":
            # remote frame
            canId = int(string[1:4], 16)
            dlc = int(string[4])
            remote = True
        elif string[0] == "R":
            # remote extended frame
            canId = int(string[1:9], 16)
            dlc = int(string[9])
            extended = True
            remote = True
        elif string[0] == "d":
            # Standard CAN FD data frame
            canId = int(string[1:4], 16)
            dlc = self.decode_hex_dlc(string[4])
            data = bytearray.fromhex(string[5 : 5 + dlc * 2])
            is_fd = True
        elif string[0] == "D":
            # Extended CAN FD data frame
            canId = int(string[1:9], 16)
            dlc = self.decode_hex_dlc(string[9])
            data = bytearray.fromhex(string[10 : 10 + dlc * 2])
            extended = True
            is_fd = True
        elif string[0] == "b":
            # CANFD Flexible Data Frame
            canId = int(string[1:4], 16)
            dlc = self.decode_hex_dlc(string[4])
            data = bytearray.fromhex(string[5 : 5 + dlc * 2])
            is_fd = True
            bitrate_switch = True
        elif string[0] == "B":
            # Extended CANFD Flexible Data Frame
            canId = int(string[1:9], 16)
            dlc = self.decode_hex_dlc(string[9])
            data = bytearray.fromhex(string[10 : 10 + dlc * 2])
            is_fd = True
            bitrate_switch = True
            extended = True

        if canId is not None:
            msg = Message(
                arbitration_id=canId,
                is_extended_id=extended,
                timestamp=time.time(),  # Better than nothing...
                is_remote_frame=remote,
                is_fd=is_fd,
                bitrate_switch=bitrate_switch,
                dlc=dlc,
                data=data,
            )
            return msg, False
        return None, False

    def encode_dlc_hex(self, data_length: int) -> str:
        if 0 <= data_length <= 8:
            return format(data_length, 'X')
        elif data_length == 12:
            return '9'
        elif data_length == 16:
            return 'A'
        elif data_length == 20:
            return 'B'
        elif data_length == 24:
            return 'C'
        elif data_length == 32:
            return 'D'
        elif data_length == 48:
            return 'E'
        return 'F'

    def send(self, msg: Message, timeout: Optional[float] = None) -> None:
        if timeout != self.serialPortOrig.write_timeout:
            self.serialPortOrig.write_timeout = timeout
		
        if msg.is_fd:
            dlc_hex = self.encode_dlc_hex(msg.dlc)
            if msg.bitrate_switch:
                if msg.is_extended_id:
                    sendStr = f"B{msg.arbitration_id:08X}{dlc_hex}"
                else:
                    sendStr = f"b{msg.arbitration_id:03X}{dlc_hex}"
            else:
                if msg.is_extended_id:
                    sendStr = f"D{msg.arbitration_id:08X}{dlc_hex}"
                else:
                    sendStr = f"d{msg.arbitration_id:03X}{dlc_hex}"
            sendStr += msg.data.hex().upper()
            if dlc_hex == 'F' and msg.dlc < 64:
                padding = '00' * (64 - msg.dlc)
                sendStr += padding
        else:
            if msg.is_remote_frame:
                if msg.is_extended_id:
                    sendStr = f"R{msg.arbitration_id:08X}{msg.dlc:d}"
                else:
                    sendStr = f"r{msg.arbitration_id:03X}{msg.dlc:d}"
            else:
                if msg.is_extended_id:
                    sendStr = f"T{msg.arbitration_id:08X}{msg.dlc:d}"
                else:
                    sendStr = f"t{msg.arbitration_id:03X}{msg.dlc:d}"
                sendStr += msg.data.hex().upper()
        self._write(sendStr)

    def shutdown(self) -> None:
        super().shutdown()
        self.close()
        with error_check("Could not close serial socket"):
            self.serialPortOrig.close()

    def fileno(self) -> int:
        try:
            return self.serialPortOrig.fileno()
        except io.UnsupportedOperation:
            raise NotImplementedError(
                "fileno is not implemented using current CAN bus on this platform"
            ) from None
        except Exception as exception:
            raise CanOperationError("Cannot fetch fileno") from exception

    def get_version(
        self, timeout: Optional[float]
    ) -> Tuple[Optional[int], Optional[int]]:
        """Get HW and SW version of the slcan interface.

        :param timeout:
            seconds to wait for version or None to wait indefinitely

        :returns: tuple (hw_version, sw_version)
            WHERE
            int hw_version is the hardware version or None on timeout
            int sw_version is the software version or None on timeout
        """
        cmd = "V"
        self._write(cmd)

        string = self._read(timeout)

        if not string:
            pass
        elif string[0] == cmd and len(string) == 6:
            # convert ASCII coded version
            hw_version = int(string[1:3])
            sw_version = int(string[3:5])
            return hw_version, sw_version

        return None, None

    def get_serial_number(self, timeout: Optional[float]) -> Optional[str]:
        """Get serial number of the slcan interface.

        :param timeout:
            seconds to wait for serial number or :obj:`None` to wait indefinitely

        :return:
            :obj:`None` on timeout or a :class:`str` object.
        """
        cmd = "N"
        self._write(cmd)

        string = self._read(timeout)

        if not string:
            pass
        elif string[0] == cmd and len(string) == 6:
            serial_number = string[1:-1]
            return serial_number

        return None
