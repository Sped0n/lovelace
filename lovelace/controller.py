import time

import numpy as np
from PySide6.QtCore import QMutex, QObject, QThread, QTimer, QWaitCondition, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from serial.tools import list_ports

from lovelace.device import Device
from lovelace.main_window import MainWindow
from lovelace.ctyper import PacketCorruptError

import pyqtgraph as pg


class Controller:
    def __init__(self) -> None:
        # device
        self.device = Device()

        # acquisition depth
        self.depth: int = 1250

        # default timebase
        self.set_timebase("5 us")

        # default channel enable
        self.channel_enable: list[bool] = [True, True]

        # default util graph content
        self.util_graph_content: str = "Region"

        # gui
        self.app = QApplication([])
        self.main_window = MainWindow(controller=self)

        # fps stat
        self.fps_timer: QTimer = QTimer()
        self.fps_timer.timeout.connect(self.update_ui_fps)
        self.spf: float = 1.0  # second per frame
        self.timestamp_last_capture: float = time.time()

        # acquisition thread
        self.continuous_acquisition: bool = False
        self.worker_wait_condition: QWaitCondition = QWaitCondition()
        self.acquisition_worker = AcquisitionWorker(
            wait_condition=self.worker_wait_condition,
            device=self.device,
            block_getter=self.worker_block_getter,
            depth_getter=self.worker_depth_getter,
        )
        self.worker_block = True
        self.acquisition_thread = QThread()
        self.acquisition_worker.moveToThread(self.acquisition_thread)
        self.acquisition_thread.started.connect(self.acquisition_worker.run)
        self.acquisition_worker.data_ready.connect(self.data_ready_callback)
        self.acquisition_thread.start()

        # on app exit
        self.app.aboutToQuit.connect(self.on_app_exit)

    def run_app(self) -> None:
        self.main_window.show()
        self.app.exec_()

    def get_ports_names(self) -> list[str]:
        return [port.device for port in list_ports.comports()]

    def update_ui_fps(self) -> None:
        fps: float = 1.0 / self.spf
        self.main_window.control_panel.stats_panel.fps_label.setText(f"{fps:.2f} fps")

    def set_timebase(self, timebase: str) -> None:
        # send timebase to device
        self.device.timebase = timebase
        if self.is_device_connected:
            self.device.write_timebase()
        # adjust timebase in the screen
        self.seconds_per_sample: float = (
            float(timebase.split()[0])
            / int(self.depth / 10)
            * {"ms": 1e-3, "us": 1e-6}[timebase.split()[1]]
        )
        self.data_time_array = np.arange(0, self.depth) * self.seconds_per_sample
        try:
            if self.util_graph_content == "Region":
                self.set_p2_xrange()
            self.set_p2_region(self.main_window.screen.region)
        except AttributeError:
            pass

    def set_trigger_state(self, on: bool) -> None:
        self.device.trigger_enable = on
        if self.is_device_connected:
            self.device.write_trigger_state()

    def set_trigger_slope(self, slope: str) -> None:
        self.device.trigger_slope = slope
        if self.is_device_connected:
            self.device.write_trigger_slope()

    def set_trigger_position(self, position: str) -> None:
        self.device.trigger_position = position
        if self.is_device_connected:
            self.device.write_trigger_state()

    def set_trigger_channel(self, channel: str) -> None:
        self.device.trigger_channel = channel
        if self.is_device_connected:
            self.device.write_trigger_channel()

    def set_trigger_threshold(self, threshold: str) -> None:
        self.device.trigger_threshold = threshold
        if self.is_device_connected:
            self.device.write_trigger_threshold()

    def set_ch1_state(self, on: bool) -> None:
        # hide or show plot
        self.main_window.screen.p1_ch1.setVisible(on)
        self.main_window.screen.p2_ch1.setVisible(on)
        # update channel enable
        self.channel_enable[0] = on
        # update channel stats
        self.channel_stats_update()

    def set_ch2_state(self, on: bool) -> None:
        # hide or show plot
        self.main_window.screen.p1_overlay.setVisible(on)
        self.main_window.screen.p2_ch2.setVisible(on)
        # update channel enable
        self.channel_enable[1] = on
        # update channel stats
        self.channel_stats_update()

    def set_util_graph_state(self, on: bool) -> None:
        self.main_window.screen.p2.setVisible(on)

    def set_p2_xrange(self) -> None:
        self.main_window.screen.p2.setXRange(
            0, (self.depth) * self.seconds_per_sample, padding=0.02
        )

    def set_p2_region(self, region: pg.LinearRegionItem) -> None:
        region.setRegion(
            [
                self.data_time_array[int(len(self.data_time_array) * 0.25)],
                self.data_time_array[int(len(self.data_time_array) * 0.75)],
            ]
        )

    def set_ch1_yrange(self, value: int) -> None:
        self.main_window.screen.p1.setYRange(-5 / value, 5 / value, padding=0.1)

    def set_ch2_yrange(self, value: int) -> None:
        self.main_window.screen.p1_overlay.setYRange(-5 / value, 5 / value, padding=0.1)

    def set_util_graph_content(self, content: str) -> None:
        match content:
            case "Region":
                self.util_graph_content = content
                self.main_window.screen.p2_ch1.setFftMode(False)
                self.main_window.screen.p2_ch2.setFftMode(False)
                self.main_window.screen.region.setVisible(True)
                self.main_window.screen.region.setMovable(True)
                self.set_p2_xrange()
                self.set_p2_region(self.main_window.screen.region)
            case "FFT":
                self.util_graph_content = content
                self.main_window.screen.region.setVisible(False)
                self.main_window.screen.region.setMovable(False)
                self.main_window.screen.p2.enableAutoRange(axis="y")
                self.main_window.screen.p2.enableAutoRange(axis="x")
                self.main_window.screen.p2_ch1.setFftMode(True)
                self.main_window.screen.p2_ch2.setFftMode(True)
            case _:
                raise ValueError(f"Unknown content: {content}")

    def connect_device(self, port: str) -> None:
        if port == "":
            QMessageBox.about(self.main_window, "Error", "Please select a port.")
        elif port not in self.get_ports_names():
            QMessageBox.about(
                self.main_window,
                "Error",
                "Could not connect to device. Port {port} not available. Refresh and try again.",  # noqa: E501
            )
        else:
            self.device.connect(port)
            self.device.write_all_settings()

    def disconnect_device(self) -> None:
        self.device.disconnect()

    @property
    def is_device_connected(self) -> bool:
        return self.device.is_connected

    def show_no_connection_message(self) -> None:
        QMessageBox.about(
            self.main_window,
            "Device not connected",
            "No device is connected. Connect a device first.",
        )

    def worker_block_getter(self) -> bool:
        return self.worker_block

    def worker_depth_getter(self) -> int:
        return self.depth

    def oscilloscope_single_run(self):
        if self.is_device_connected:
            self.continuous_acquisition = False
            self.worker_block = False
            self.device.clean_buffers()
            self.worker_wait_condition.notify_one()
            return True
        else:
            self.show_no_connection_message()
            return False

    def oscilloscope_continuous_run(self):
        if self.is_device_connected:
            self.timestamp_last_capture = time.time()
            self.spf = 1
            self.fps_timer.start(500)
            self.continuous_acquisition = True
            self.worker_block = False
            self.device.clean_buffers()
            self.worker_wait_condition.notify_one()
            return True
        else:
            self.show_no_connection_message()
            return False

    def oscilloscope_stop(self):
        self.continuous_acquisition = False
        self.fps_timer.stop()

    def channel_stats_update(self):
        for ch, panel in enumerate(
            [
                self.main_window.control_panel.ch1_panel,
                self.main_window.control_panel.ch2_panel,
            ]
        ):
            if self.channel_enable[ch]:
                # voltage
                panel.vmax_value.setText(
                    f"{np.max(self.acquisition_worker.data[ch]):.2f} V"
                )
                panel.vmin_value.setText(
                    f"{np.min(self.acquisition_worker.data[ch]):.2f} V"
                )
                panel.vpp_value.setText(
                    f"{np.ptp(self.acquisition_worker.data[ch]):.2f} V"
                )
                # frequency
                fft = np.fft.fft(self.acquisition_worker.data[ch])
                fftfreq = np.fft.fftfreq(self.depth, self.seconds_per_sample)
                panel.freq_value.setText(
                    f"{abs(fftfreq[np.argmax(np.abs(fft))]):.3g} Hz"
                )
            else:
                panel.vmax_value.setText("N/A")
                panel.vmin_value.setText("N/A")
                panel.vpp_value.setText("N/A")
                panel.freq_value.setText("N/A")

    def data_ready_callback(self):
        try:
            curr_time = time.time()
            self.spf = 0.9 * (curr_time - self.timestamp_last_capture) + 0.1 * self.spf
            self.timestamp_last_capture = curr_time
            if self.acquisition_worker.data_valid:
                self.main_window.screen.update_ch(
                    self.data_time_array,
                    self.acquisition_worker.data,
                )
                self.channel_stats_update()
        finally:
            if self.continuous_acquisition:
                self.worker_block = False
                self.worker_wait_condition.notify_one()
            else:
                self.worker_block = True

    def on_app_exit(self):
        # stop worker
        self.acquisition_worker.stop()
        self.worker_block = False
        self.worker_wait_condition.notify_one()
        # disconnect device
        self.disconnect_device()
        # quit thread
        self.acquisition_thread.quit()
        # wait thread to finish
        self.acquisition_thread.wait()
        # print
        print("exiting")


class AcquisitionWorker(QObject):
    data_ready = Signal()

    def __init__(self, wait_condition, device, block_getter, depth_getter, parent=None):
        super().__init__(parent=parent)
        # for synchronization
        self.wait_condition = wait_condition
        self.block_getter = block_getter
        self.depth_getter = depth_getter
        self.mutex = QMutex()
        # for safely quit
        self.is_running: bool = False
        # device
        self.device = device
        # data
        self.data_valid: bool = False

    def run(self):
        if not self.is_running:
            self.is_running = True
        while True:
            time.sleep(0.01)
            while self.block_getter():
                self.mutex.lock()
                self.wait_condition.wait(self.mutex)
                self.mutex.unlock()
            if not self.is_running:
                break
            try:
                self.device.clean_buffers("input")
                self.data = self.device.acquire_single()
                self.data_valid = True
            except PacketCorruptError:
                self.data = [
                    np.zeros(self.depth_getter()),
                    np.zeros(self.depth_getter()),
                ]
                self.data_valid = False
            finally:
                self.data_ready.emit()
        print("finished")

    def stop(self):
        self.is_running = False
