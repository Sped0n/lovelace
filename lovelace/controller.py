import time

import numpy as np
from PySide6.QtCore import QMutex, QObject, QThread, QTimer, QWaitCondition, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from serial.tools import list_ports

from lovelace.device import Device
from lovelace.main_window import MainWindow
from lovelace.ctyper import PacketCorruptError


class Controller:
    def __init__(self) -> None:
        # gui
        self.app = QApplication([])
        self.main_window = MainWindow(controller=self)

        # device
        self.device = Device()

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
        )
        self.worker_block = True
        self.acquisition_thread = QThread()
        self.acquisition_worker.moveToThread(self.acquisition_thread)
        self.acquisition_thread.started.connect(self.acquisition_worker.run)
        self.acquisition_worker.finished.connect(self.acquisition_thread.quit)
        self.acquisition_worker.data_ready.connect(self.data_ready_callback)
        self.acquisition_thread.start()

        # default timebase
        self.set_timebase("20 ms")

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
        seconds_per_sample: float = (
            float(timebase.split()[0])
            / 25
            * {"ms": 1e-3, "us": 1e-6}[timebase.split()[1]]
        )
        self.device.set_timeout(seconds_per_sample)
        self.data_time_array = np.arange(0, 250) * seconds_per_sample
        self.main_window.screen.setXRange(0, (250) * seconds_per_sample, padding=0.02)
        self.main_window.screen.setYRange(-5, 5)

    def set_trigger_state(self, on: bool) -> None:
        self.device.trigger_enable = on
        if self.is_device_connected:
            self.device.write_trigger_state()

    def set_trigger_slope(self, slope: str) -> None:
        self.device.trigger_slope = slope
        if self.is_device_connected:
            self.device.write_trigger_slope()

    def set_ch1_yrange(self, value: int) -> None:
        self.main_window.screen.setYRange(-5 / value, 5 / value)

    def set_ch2_yrange(self, value: int) -> None:
        self.main_window.screen.overlay.setYRange(-5 / value, 5 / value)

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

    def worker_block_getter(self):
        return self.worker_block

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

    def data_ready_callback(self):
        try:
            curr_time = time.time()
            self.spf = 0.9 * (curr_time - self.timestamp_last_capture) + 0.1 * self.spf
            self.timestamp_last_capture = curr_time
            self.main_window.screen.update_ch(
                self.data_time_array, self.acquisition_worker.data
            )
        finally:
            if self.continuous_acquisition:
                print("callback")
                self.worker_block = False
                self.worker_wait_condition.notify_one()
            else:
                self.worker_block = True

    def on_app_exit(self):
        print("exiting")


class AcquisitionWorker(QObject):
    finished = Signal()
    data_ready = Signal()

    def __init__(self, wait_condition, device, block_getter, parent=None):
        super().__init__(parent=parent)
        self.wait_condition = wait_condition
        self.device = device
        self.block_getter = block_getter
        self.mutex = QMutex()
        self.empty_data = [np.zeros(250), np.zeros(250)]

    def run(self):
        try:
            while True:
                print("waiting mutex")
                while self.block_getter():
                    self.mutex.lock()
                    self.wait_condition.wait(self.mutex)
                    self.mutex.unlock()
                try:
                    self.device.clean_buffers("input")
                    self.data = self.device.acquire_single()
                except PacketCorruptError:
                    print("Packet corrupt")
                    self.data = self.empty_data
                finally:
                    print("--------------")
                    self.data_ready.emit()
        except Exception as e:
            print(e)
            self.finished.emit()
