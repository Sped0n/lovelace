import time

import numpy as np
import serial

from lovelace.ctyper import CmdContentError, CmdTypeError, PacketCorruptError
from lovelace.utils import bytepack, gen_packet_content


class Device:
    BAUDRATE = 2000000
    BUFFERSIZE = 2505

    def __init__(self) -> None:
        # pyserial instance
        self.serial_port: serial.Serial = serial.Serial()
        self.serial_port.timeout = 0.5
        self.serial_port.baudrate = self.BAUDRATE
        # default config
        self.timebase: str = "5 us"
        self.trigger_enable: bool = False
        self.trigger_position: str = "0%"
        self.trigger_channel: str = "CH1"
        self.trigger_slope: str = "rising"
        self.trigger_threshold: str = "128"

    def connect(self, port: str) -> None:
        print(port)
        self.serial_port.port = port
        self.serial_port.open()
        time.sleep(1)

    def disconnect(self) -> None:
        self.serial_port.close()

    @property
    def is_connected(self) -> bool:
        return self.serial_port.is_open

    def write_all_settings(self) -> None:
        self.write_timebase()
        self.write_trigger_state()
        self.write_trigger_channel()
        self.write_trigger_threshold()
        self.write_trigger_slope()

    def write_timebase(self) -> None:
        self.serial_port.write(self.__gen_cmd("timebase", self.timebase))

    def write_trigger_state(self) -> None:
        if self.trigger_enable:
            self.serial_port.write(self.__gen_cmd("trigger", self.trigger_position))
        else:
            self.serial_port.write(self.__gen_cmd("trigger", "disable"))

    def write_trigger_channel(self) -> None:
        self.serial_port.write(self.__gen_cmd("trigger_channel", self.trigger_channel))

    def write_trigger_threshold(self) -> None:
        self.serial_port.write(
            self.__gen_cmd("trigger_threshold", self.trigger_threshold)
        )

    def write_trigger_slope(self) -> None:
        self.serial_port.write(self.__gen_cmd("trigger_slope", self.trigger_slope))

    def clean_buffers(self, option: str = "") -> None:
        if option == "input":
            self.serial_port.reset_input_buffer()
        elif option == "output":
            self.serial_port.reset_output_buffer()
        else:
            self.serial_port.reset_input_buffer()
            self.serial_port.reset_output_buffer()

    def acquire_single(self, eager: bool = True) -> list[np.ndarray]:
        buf = bytes()
        request_sended: bool = False
        last_buf_len: int = -1
        corrupted: bool = False
        while True:
            if eager:  # resend request if data corrupted
                if not request_sended and not corrupted:
                    self.serial_port.write(self.__gen_cmd("request"))
                else:
                    self.serial_port.write(self.__gen_cmd("resend"))
            else:  # ignore corrupted data, keep waiting for new data
                if not request_sended:
                    self.serial_port.write(self.__gen_cmd("request"))
            # read data
            time.sleep(0.01)
            tmp: bytes = self.serial_port.read(self.serial_port.in_waiting)
            buf += tmp
            if not request_sended and len(buf) > 0:
                request_sended = True
            if len(buf) == last_buf_len:
                self.serial_port.close()
                self.serial_port.open()
                self.write_all_settings()
                raise PacketCorruptError("packet corrupt")
            # parse data
            if len(buf) >= self.BUFFERSIZE:
                data: np.ndarray = np.frombuffer(buf, dtype=np.uint8).astype(float)[
                    0 : self.BUFFERSIZE
                ]
                # reset buffer
                buf = bytes()
                if int(data[0]) == 85 and int(data[1]) == 1:
                    data = data[4:-1] * 10 / 256 - 5
                    res: list[np.ndarray] = [data[0:1250], data[1250:]]
                    break
                else:
                    corrupted = True
                    self.clean_buffers("input")
            last_buf_len = len(buf)
        return res

    def __gen_cmd(self, cmd_type: str, cmd_content: str = "") -> bytearray:
        packet_content: list[int] = []
        match cmd_type:
            case "request":
                packet_content = gen_packet_content(7, [1])
            case "resend":
                packet_content = gen_packet_content(8, [1])
            case "timebase":
                match cmd_content:
                    case "5 us":
                        packet_content = gen_packet_content(6, [0])
                    case "10 us":
                        packet_content = gen_packet_content(6, [1])
                    case "25 us":
                        packet_content = gen_packet_content(6, [2])
                    case "50 us":
                        packet_content = gen_packet_content(6, [3])
                    case "100 us":
                        packet_content = gen_packet_content(6, [4])
                    case "250 us":
                        packet_content = gen_packet_content(6, [5])
                    case "500 us":
                        packet_content = gen_packet_content(6, [6])
                    case "1 ms":
                        packet_content = gen_packet_content(6, [7])
                    case "2.5 ms":
                        packet_content = gen_packet_content(6, [8])
                    case "5 ms":
                        packet_content = gen_packet_content(6, [9])
                    case "10 ms":
                        packet_content = gen_packet_content(6, [10])
                    case "25 ms":
                        packet_content = gen_packet_content(6, [11])
                    case "50 ms":
                        packet_content = gen_packet_content(6, [12])
                    case "100 ms":
                        packet_content = gen_packet_content(6, [13])
                    case "250 ms":
                        packet_content = gen_packet_content(6, [14])
                    case _:
                        raise CmdContentError(f"invalid timebase: {cmd_content}")
            case "trigger":
                match cmd_content:
                    case "disable":
                        packet_content = gen_packet_content(4, [5])
                    case "0%":
                        packet_content = gen_packet_content(4, [0])
                    case "25%":
                        packet_content = gen_packet_content(4, [1])
                    case "50%":
                        packet_content = gen_packet_content(4, [2])
                    case "75%":
                        packet_content = gen_packet_content(4, [3])
                    case "100%":
                        packet_content = gen_packet_content(4, [4])
                    case _:
                        raise CmdContentError(f"invalid trigger: {cmd_content}")
            case "trigger_channel":
                match cmd_content:
                    case "CH1":
                        packet_content = gen_packet_content(5, [0])
                    case "CH2":
                        packet_content = gen_packet_content(5, [1])
                    case _:
                        raise CmdContentError(f"invalid trigger channel: {cmd_content}")
            case "trigger_slope":
                match cmd_content:
                    case "rising":
                        packet_content = gen_packet_content(3, [1])
                    case "falling":
                        packet_content = gen_packet_content(3, [0])
                    case _:
                        raise CmdContentError(f"invalid trigger edge: {cmd_content}")
            case "trigger_threshold":
                if 0 <= int(cmd_content) <= 255:
                    packet_content = gen_packet_content(2, [int(cmd_content)])
                else:
                    raise CmdContentError(f"invalid trigger threshold: {cmd_content}")
            case _:
                raise CmdTypeError(f"invalid command type: {cmd_type}")
        packet_content.insert(0, 85)
        return bytepack(packet_content)
