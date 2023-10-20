import ftd2xx as d2xx
import numpy as np

from lovelace.ctyper import (
    CmdContentError,
    CmdTypeError,
    NoConnectionError,
    PacketCorruptError,
)
from lovelace.utils import bytepack, gen_packet_content


class Device:
    def __init__(
        self, device_name: str = "USB <-> Serial Cable", chunk_size: int = 65536
    ) -> None:
        # d2xx instance
        self.device_name: str = device_name
        self.__chunk_size: int = chunk_size
        self.__usb: d2xx.FTD2XX | None = None
        self.connected: bool = False
        self.__recv_timeout: int = 4000
        self.__send_timeout: int = 4000
        # default config
        self.timebase: str = "5 us"
        self.trigger_enable: bool = False
        self.trigger_position: str = "0"
        self.trigger_channel: str = "CH1"
        self.trigger_slope: str = "rising"
        self.trigger_threshold: str = "128"
        self.sample_rate: str = "25 MHz"
        self.sample_depth: str = "1250"

    def connect(self) -> None:
        b_device_name: bytes = bytes(self.device_name, encoding="ASCII")
        for i in range(16):
            try:
                tmp = d2xx.open(i)
                if tmp.getDeviceInfo()["description"] == b_device_name:
                    print("found device")
                    self.connected = True
                    # config
                    self.__usb = tmp
                    self.__usb.setBitMode(0xFF, 0x40)
                    self.__usb.setUSBParameters(
                        self.__chunk_size * 4, self.__chunk_size * 4
                    )
                    self.set_recv_timeout(self.__recv_timeout)
                    self.set_send_timeout(self.__send_timeout)
                    break
                else:
                    tmp.close()
            except d2xx.DeviceError:
                pass

    def disconnect(self) -> None:
        if self.__usb is None:
            return None
        self.__usb.close()
        self.__usb = None
        self.connected = False

    def recv(self, recv_len) -> bytes:
        if self.__usb is None:
            raise NoConnectionError("no connection")
        # init
        data: bytes = bytes()
        for si in range(0, recv_len, self.__chunk_size):
            ei = si + self.__chunk_size
            ei = min(ei, recv_len)

            chunk_len = ei - si
            chunk: bytes = self.__usb.read(chunk_len)
            data += chunk  # type: ignore
            if len(chunk) < chunk_len:
                break
        return data

    def set_recv_timeout(self, timeout: int) -> None:
        self.__recv_timeout = timeout
        if self.__usb is None:
            return None
        self.__usb.setTimeouts(self.__recv_timeout, self.__send_timeout)

    def set_send_timeout(self, timeout: int) -> None:
        self.__send_timeout = timeout
        if self.__usb is None:
            return None
        self.__usb.setTimeouts(self.__recv_timeout, self.__send_timeout)

    def write_all_settings(self) -> None:
        self.write_sample_rate()
        self.write_sample_depth()
        self.write_trigger_state()
        self.write_trigger_channel()
        self.write_trigger_threshold()
        self.write_trigger_slope()

    def write_sample_rate(self) -> None:
        if self.__usb is None:
            return None
        self.__usb.write(self.__gen_cmd("sample_rate", self.sample_rate))

    def write_sample_depth(self) -> None:
        if self.__usb is None:
            return None
        self.__usb.write(self.__gen_cmd("sample_depth", self.sample_depth))

    def write_trigger_state(self) -> None:
        if self.__usb is None:
            return None
        if self.trigger_enable:
            self.__usb.write(self.__gen_cmd("trigger", self.trigger_position))
        else:
            self.__usb.write(self.__gen_cmd("trigger", "disable"))

    def write_trigger_channel(self) -> None:
        if self.__usb is None:
            return None
        self.__usb.write(self.__gen_cmd("trigger_channel", self.trigger_channel))

    def write_trigger_threshold(self) -> None:
        if self.__usb is None:
            return None
        self.__usb.write(self.__gen_cmd("trigger_threshold", self.trigger_threshold))

    def write_trigger_slope(self) -> None:
        if self.__usb is None:
            return None
        self.__usb.write(self.__gen_cmd("trigger_slope", self.trigger_slope))

    def acquire_single(self) -> list[float]:
        if self.__usb is None:
            raise NoConnectionError("no connection")
        res: list[float] = []
        for i in range(int(int(self.sample_depth) * 2 / 500)):
            while True:
                # send request
                if i == 0:
                    self.__usb.write(self.__gen_cmd("request"))
                else:
                    self.__usb.write(self.__gen_cmd("depack"))
                # read data
                # if no data, retry
                if self.__usb.getQueueStatus() == 0:
                    continue
                # get one packet
                get: bytes = self.recv(505)
                # decode
                data: np.ndarray = np.frombuffer(get, dtype=np.uint8).astype(float)
                # packet length check
                if len(data) != 505:
                    # abort
                    self.__usb.write(self.__gen_cmd("resend"))
                    raise PacketCorruptError(f"data length error, {len(data)} != 505")
                # id / packet header check
                if int(data[1]) != i or int(data[0]) != 85:
                    # abort
                    self.__usb.write(self.__gen_cmd("resend"))
                    raise PacketCorruptError(
                        f"data id or header error, id{int(data[1])} != id{i}"
                    )
                # checksum
                if sum(data[:-1]) % 256 == data[-1]:
                    res += (data[4:-1] * 10 / 256 - 5).tolist()
                else:
                    # abort
                    self.__usb.write(self.__gen_cmd("resend"))
                    raise PacketCorruptError("checksum error")
                break
        return res

    def __gen_cmd(self, cmd_type: str, cmd_content: str = "") -> bytes:
        packet_content: list[int] = []
        match cmd_type:
            case "request":
                packet_content = gen_packet_content(7, [1])
            case "resend":
                packet_content = gen_packet_content(8, [1])
            case "depack":
                packet_content = gen_packet_content(9, [1])
            case "sample_rate":
                match cmd_content:
                    case "25 MHz":
                        packet_content = gen_packet_content(6, [0])
                    case "12.5 MHz":
                        packet_content = gen_packet_content(6, [1])
                    case "5 MHz":
                        packet_content = gen_packet_content(6, [2])
                    case "2.5 MHz":
                        packet_content = gen_packet_content(6, [3])
                    case "1.25 MHz":
                        packet_content = gen_packet_content(6, [4])
                    case "500 kHz":
                        packet_content = gen_packet_content(6, [5])
                    case "250 kHz":
                        packet_content = gen_packet_content(6, [6])
                    case "125 kHz":
                        packet_content = gen_packet_content(6, [7])
                    case "50 kHz":
                        packet_content = gen_packet_content(6, [8])
                    case "25 kHz":
                        packet_content = gen_packet_content(6, [9])
                    case "12.5 kHz":
                        packet_content = gen_packet_content(6, [10])
                    case "5 kHz":
                        packet_content = gen_packet_content(6, [11])
                    case "2.5 kHz":
                        packet_content = gen_packet_content(6, [12])
                    case "1.25 kHz":
                        packet_content = gen_packet_content(6, [13])
                    case "500 Hz":
                        packet_content = gen_packet_content(6, [14])
                    case _:
                        raise CmdContentError(f"invalid timebase: {cmd_content}")
            case "sample_depth":
                match cmd_content:
                    case "1250":
                        packet_content = gen_packet_content(10, [0])
                    case "2500":
                        packet_content = gen_packet_content(10, [1])
                    case "5000":
                        packet_content = gen_packet_content(10, [2])
                    case "12500":
                        packet_content = gen_packet_content(10, [3])
                    case _:
                        raise CmdContentError(f"invalid sample depth: {cmd_content}")
            case "trigger":
                match cmd_content:
                    case "disable":
                        packet_content = gen_packet_content(4, [255, 255])
                    case _:
                        if 0 <= int(cmd_content) <= 65535:
                            packet_content = gen_packet_content(
                                4, [int(cmd_content) // 256, int(cmd_content) % 256]
                            )
                        else:
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
