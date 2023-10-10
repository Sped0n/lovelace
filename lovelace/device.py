import time

import numpy as np
import serial

from lovelace.ctyper import CmdContentError, CmdTypeError, PacketCorruptError
from lovelace.utils import bytepack, gen_packet_content


class Device:
    BAUDRATE = 1000000
    BUFFERSIZE = 516

    def __init__(self) -> None:
        # pyserial instance
        self.serial_port: serial.Serial = serial.Serial()
        self.serial_port.timeout = 0.5
        self.serial_port.baudrate = self.BAUDRATE
        # default config
        self.timebase: str = "1 us"
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

    def set_timeout(self, sps: float) -> None:
        # 1.5 times of the seconds per acquisition
        self.serial_port.timeout = 1.5 * self.BUFFERSIZE * (sps + 11 / self.BAUDRATE)

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

    def acquire_single(self) -> list[np.ndarray]:
        self.serial_port.write(self.__gen_cmd("request"))
        # read data
        print("waiting for data")
        tmp: bytes = self.serial_port.read(self.BUFFERSIZE)
        # parse data
        data: np.ndarray = np.frombuffer(tmp, dtype=np.uint8).astype(float)
        if len(data) == self.BUFFERSIZE and int(data[0]) == 85 and int(data[1]) == 1:
            data = data[4:-1] * 10 / 256 - 5
        else:
            raise PacketCorruptError("packet corrupt")
        res: list[np.ndarray] = [data[:250], data[256:-5]]
        return res

    def __gen_cmd(self, cmd_type: str, cmd_content: str = "") -> bytearray:
        packet_content: list[int] = []
        match cmd_type:
            case "request":
                packet_content = gen_packet_content(7, [1])
            case "timebase":
                match cmd_content:
                    case "1 us":
                        packet_content = gen_packet_content(6, [0])
                    case "2 us":
                        packet_content = gen_packet_content(6, [1])
                    case "5 us":
                        packet_content = gen_packet_content(6, [2])
                    case "10 us":
                        packet_content = gen_packet_content(6, [3])
                    case "20 us":
                        packet_content = gen_packet_content(6, [4])
                    case "50 us":
                        packet_content = gen_packet_content(6, [5])
                    case "100 us":
                        packet_content = gen_packet_content(6, [6])
                    case "200 us":
                        packet_content = gen_packet_content(6, [7])
                    case "500 us":
                        packet_content = gen_packet_content(6, [8])
                    case "1 ms":
                        packet_content = gen_packet_content(6, [9])
                    case "2 ms":
                        packet_content = gen_packet_content(6, [10])
                    case "5 ms":
                        packet_content = gen_packet_content(6, [11])
                    case "10 ms":
                        packet_content = gen_packet_content(6, [12])
                    case "20 ms":
                        packet_content = gen_packet_content(6, [13])
                    case "50 ms":
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
