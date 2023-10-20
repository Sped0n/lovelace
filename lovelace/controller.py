import time

import numpy as np
from PySide6.QtCore import QMutex, QObject, QThread, QTimer, QWaitCondition, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from lovelace.ctyper import PacketCorruptError
from lovelace.device import Device
from lovelace.main_window import MainWindow


class Controller:
    def __init__(self) -> None:
        # device
        self.__device = Device()

        # default config
        # we set up this because we need to parse some value to main window
        self.__update_sps_dta()
        self.channel_enable: list[bool] = [True, True]
        self.__util_graph_content: str = "Region"

        # gui
        self.__app = QApplication([])
        self.__main_window = MainWindow(controller=self)

        # fps stat
        self.__fps_timer: QTimer = QTimer()
        self.__fps_timer.timeout.connect(self.__update_ui_fps)
        self.__spf: float = 1.0  # second per frame
        self.__timestamp_last_capture: float = time.time()

        # acquisition thread
        # config
        self.__worker_block = True
        self.continuous_acquisition: bool = False
        # thread setup
        self.__worker_wait_condition: QWaitCondition = QWaitCondition()
        self.__acquisition_worker = AcquisitionWorker(
            wait_condition=self.__worker_wait_condition,
            device=self.__device,
            block_getter=self.__worker_block_getter,
            depth_getter=self.__worker_depth_getter,
        )
        self.__acquisition_thread = QThread()
        self.__acquisition_worker.moveToThread(self.__acquisition_thread)
        self.__acquisition_thread.started.connect(self.__acquisition_worker.run)
        self.__acquisition_worker.data_ready.connect(self.__data_ready_callback)
        self.__acquisition_thread.start()

        # on app exit
        self.__app.aboutToQuit.connect(self.__on_app_exit)

    # properties

    @property
    def is_device_connected(self) -> bool:
        # status
        return self.__device.connected

    @property
    def depth(self) -> int:
        # depth
        return int(self.__device.sample_depth)

    # public methods

    def run_app(self) -> None:
        self.__main_window.show()
        self.__app.exec_()

    def set_sample_rate(self, sample_rate: str) -> None:
        # set device sample rate
        self.__device.sample_rate = sample_rate
        if self.is_device_connected:
            self.__device.write_sample_rate()
        # adjust display x scale param
        self.__update_sps_dta()
        # update equivalent time
        self.__update_equiv_time()
        # set display x scale
        self.__set_x_display_scale()

    def set_sample_depth(self, depth: str) -> None:
        # set device sample depth
        self.__device.sample_depth = depth
        if self.is_device_connected:
            self.__device.write_sample_depth()
        # adjust display x scale param
        self.__update_sps_dta()
        # update equivalent time
        self.__update_equiv_time()
        # set display x scale
        self.__set_x_display_scale()

    def set_trigger_state(self, on: bool) -> None:
        # set device trigger enable
        self.__device.trigger_enable = on
        if self.is_device_connected:
            self.__device.write_trigger_state()

    def set_trigger_slope(self, slope: str) -> None:
        # set device trigger slope
        self.__device.trigger_slope = slope
        if self.is_device_connected:
            self.__device.write_trigger_slope()

    def set_trigger_position(self, position: str) -> None:
        # set device trigger position
        self.__device.trigger_position = position
        if self.is_device_connected:
            self.__device.write_trigger_state()

    def set_trigger_channel(self, channel: str) -> None:
        # set device trigger channel
        self.__device.trigger_channel = channel
        if self.is_device_connected:
            self.__device.write_trigger_channel()

    def set_trigger_threshold(self, threshold: str) -> None:
        # set device trigger threshold
        self.__device.trigger_threshold = threshold
        if self.is_device_connected:
            self.__device.write_trigger_threshold()

    def set_ch1_state(self, on: bool) -> None:
        # hide or show plot
        self.__main_window.screen.p1_ch1.setVisible(on)
        self.__main_window.screen.p2_ch1.setVisible(on)
        # update channel enable
        self.channel_enable[0] = on
        # update channel stats
        self.__update_channel_stats()

    def set_ch2_state(self, on: bool) -> None:
        # hide or show plot
        self.__main_window.screen.p1_overlay.setVisible(on)
        self.__main_window.screen.p2_ch2.setVisible(on)
        # update channel enable
        self.channel_enable[1] = on
        # update channel stats
        self.__update_channel_stats()

    def set_util_graph_state(self, on: bool) -> None:
        # hide utility graph completely
        self.__main_window.screen.p2.setVisible(on)

    def set_ch1_yrange(self, value: int) -> None:
        # set channel 1 y range
        self.__main_window.screen.p1.setYRange(-5 / value, 5 / value, padding=0.1)

    def set_ch2_yrange(self, value: int) -> None:
        # set channel 2 y range
        self.__main_window.screen.p1_overlay.setYRange(
            -5 / value, 5 / value, padding=0.1
        )

    def set_util_graph_content(self, content: str) -> None:
        match content:
            case "Reset":
                # save current mode
                self.__util_graph_content = content
                # FFT false
                self.__main_window.screen.p2_ch1.setFftMode(False)
                self.__main_window.screen.p2_ch2.setFftMode(False)
                # show region
                self.__main_window.screen.region.setVisible(True)
                self.__main_window.screen.region.setMovable(True)
                # reset x range
                self.__main_window.screen.update_p2_xrange()
                # reanchor region
                self.__main_window.screen.reanchor_p2_region()
            case "Region":
                # save current mode
                self.__util_graph_content = content
                # FFT false
                self.__main_window.screen.p2_ch1.setFftMode(False)
                self.__main_window.screen.p2_ch2.setFftMode(False)
                # show region
                self.__main_window.screen.region.setVisible(True)
                self.__main_window.screen.region.setMovable(True)
                # reset x range
                self.__main_window.screen.update_p2_xrange()
            case "FFT":
                # save current mode
                self.__util_graph_content = content
                # hide region
                self.__main_window.screen.region.setVisible(False)
                # set auto range for FFT graph
                self.__main_window.screen.p2.enableAutoRange(axis="y")
                self.__main_window.screen.p2.enableAutoRange(axis="x")
                # set x limit for FFT
                self.__main_window.screen.p2.setLimits(
                    xMin=0,
                    xMax=(
                        float(self.__device.sample_rate.split()[0])
                        * {"MHz": 1e6, "kHz": 1e3, "Hz": 1}[
                            self.__device.sample_rate.split()[1]
                        ]
                        / 5
                    ),
                )
                # FFT true
                self.__main_window.screen.p2_ch1.setFftMode(True)
                self.__main_window.screen.p2_ch2.setFftMode(True)
            case _:
                raise ValueError(f"Unknown content: {content}")

    def connect_device(self) -> None:
        # connect device
        self.__device.connect()
        # write settings
        self.__device.write_all_settings()

    def disconnect_device(self) -> None:
        # disconnect device
        self.__device.disconnect()

    def oscilloscope_single_run(self) -> bool:
        if self.is_device_connected:
            # single run
            self.continuous_acquisition = False
            # ensure we don't block at first iter
            self.__worker_block = False
            # notify
            self.__worker_wait_condition.notify_one()
            return True
        else:
            self.__show_no_connection_message()
            return False

    def oscilloscope_continuous_run(self) -> bool:
        if self.is_device_connected:
            # fps related stuff
            self.__timestamp_last_capture = time.time()
            self.__spf = 1
            self.__fps_timer.start(500)
            # continuous run
            self.continuous_acquisition = True
            # ensure we don't block at first iter
            self.__worker_block = False
            # notify
            self.__worker_wait_condition.notify_one()
            return True
        else:
            self.__show_no_connection_message()
            return False

    def oscilloscope_stop(self) -> None:
        # stop
        self.__worker_block = True
        self.continuous_acquisition = False
        # stop fps timer
        self.__fps_timer.stop()

    # private methods

    def __update_ui_fps(self) -> None:
        fps: float = 1.0 / self.__spf
        self.__main_window.control_panel.stats_panel.fps_label.setText(f"{fps:.2f} fps")

    def __update_sps_dta(self) -> None:
        # seconds per sample
        self.seconds_per_sample: float = 1 / (
            float(self.__device.sample_rate.split()[0])
            * {"MHz": 1e6, "kHz": 1e3, "Hz": 1}[self.__device.sample_rate.split()[1]]
        )
        # data time array
        self.data_time_array = np.arange(0, self.depth) * self.seconds_per_sample

    def __update_equiv_time(self) -> None:
        t: float = self.seconds_per_sample * self.depth
        if t > 1:
            c = f"{t:.2f} s"
        elif t > 1e-3:
            c = f"{t*1e3:.2f} ms"
        else:
            c = f"{t*1e6:.2f} us"
        self.__main_window.control_panel.time_panel.equiv_time.setText(c)

    def __set_x_display_scale(self) -> None:
        # do not reset x range when in FFT mode
        if self.__util_graph_content == "Region":
            self.__main_window.screen.update_p2_xrange()
        elif self.__util_graph_content == "FFT":
            self.__main_window.screen.p2.setLimits(
                xMin=0,
                xMax=(
                    float(self.__device.sample_rate.split()[0])
                    * {"MHz": 1e6, "kHz": 1e3, "Hz": 1}[
                        self.__device.sample_rate.split()[1]
                    ]
                    / 5
                ),
            )
        # reanchor region
        self.__main_window.screen.reanchor_p2_region()

    def __show_no_connection_message(self) -> None:
        # show message
        QMessageBox.about(
            self.__main_window,
            "Device not connected",
            "No device is connected. Connect a device first.",
        )

    def __worker_block_getter(self) -> bool:
        # for acquisition thread to get block status
        return self.__worker_block

    def __worker_depth_getter(self) -> int:
        # for acquisition thread to get acquisition depth
        return self.depth

    def __update_channel_stats(self):
        # we try here because the index will be out of range when
        # acquisition depth is changed in the middle of a run
        try:
            for ch, panel in enumerate(
                [
                    self.__main_window.control_panel.ch1_panel,
                    self.__main_window.control_panel.ch2_panel,
                ]
            ):
                if self.channel_enable[ch]:
                    # voltage
                    panel.vmax_value.setText(
                        f"{np.max(self.__acquisition_worker.data[ch]):.2f} V"
                    )
                    panel.vmin_value.setText(
                        f"{np.min(self.__acquisition_worker.data[ch]):.2f} V"
                    )
                    panel.vpp_value.setText(
                        f"{np.ptp(self.__acquisition_worker.data[ch]):.2f} V"
                    )
                    # frequency
                    fft = np.fft.fft(self.__acquisition_worker.data[ch])
                    fftfreq = np.fft.fftfreq(self.depth, self.seconds_per_sample)
                    # we try here because the index will be out of range when
                    # acquisition depth is changed in the middle of a run
                    try:
                        panel.freq_value.setText(
                            f"{abs(fftfreq[np.argmax(np.abs(fft))]):.2g} Hz"
                        )
                    except IndexError:
                        pass
                else:
                    panel.vmax_value.setText("N/A")
                    panel.vmin_value.setText("N/A")
                    panel.vpp_value.setText("N/A")
                    panel.freq_value.setText("N/A")
        except ValueError:
            pass

    def __data_ready_callback(self):
        try:
            # fps related stuff
            curr_time = time.time()
            self.__spf = (
                0.9 * (curr_time - self.__timestamp_last_capture) + 0.1 * self.__spf
            )
            self.__timestamp_last_capture = curr_time
            # if data is valid, update plot and stats
            if self.__acquisition_worker.data_valid:
                self.__main_window.screen.update_ch(
                    self.data_time_array,
                    self.__acquisition_worker.data,
                )
                self.__update_channel_stats()
        finally:
            if self.continuous_acquisition:
                # unblock and notify
                self.__worker_block = False
                self.__worker_wait_condition.notify_one()
            else:
                # block single run after first iter
                self.__worker_block = True

    def __on_app_exit(self):
        # stop worker
        self.__acquisition_worker.stop()
        self.__worker_block = False
        self.__worker_wait_condition.notify_one()
        # disconnect device
        self.disconnect_device()
        # quit thread
        self.__acquisition_thread.quit()
        # wait thread to finish
        self.__acquisition_thread.wait()
        # print
        print("exiting")


class AcquisitionWorker(QObject):
    data_ready = Signal()

    def __init__(self, wait_condition, device, block_getter, depth_getter, parent=None):
        super().__init__(parent=parent)
        # for synchronization
        self.__wait_condition = wait_condition
        self.__block_getter = block_getter
        self.__depth_getter = depth_getter
        self.__mutex = QMutex()
        # for safely quit
        self.__is_running: bool = False
        # device
        self.__device = device
        # data valid
        self.data_valid: bool = False

    def run(self):
        # init
        if not self.__is_running:
            self.__is_running = True
        while True:
            # double layer machininism to block
            while self.__block_getter():
                self.__mutex.lock()
                self.__wait_condition.wait(self.__mutex)
                self.__mutex.unlock()
            # for safely quit
            if not self.__is_running:
                break
            # acquire data
            d: int = self.__depth_getter()
            try:
                tmp = self.__device.acquire_single()
                # split channel 1 and channel 2
                self.data = [np.array(tmp[0:d]), np.array(tmp[d:])]
                self.data_valid = True
            except PacketCorruptError:
                # if packet is corrupt, we fill the data with zeros
                self.data = [
                    np.zeros(d),
                    np.zeros(d),
                ]
                self.data_valid = False
            finally:
                self.data_ready.emit()
        print("finished")

    def stop(self):
        self.__is_running = False
