import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class OscilloscopeScreen(pg.GraphicsLayoutWidget):
    def __init__(self, controller, parent=None, **kargs):
        super().__init__(parent=parent, show=True, **kargs)

        self.controller = controller

        styles = {"color": "#ffffff", "font-size": "12px"}

        self.p1 = self.addPlot(row=1, col=0, rowspan=2)

        # main plot window (channel 1) axis label setting
        self.p1.getAxis("left").setLabel("V (CH1)", **styles)
        self.p1.getAxis("bottom").setLabel("bottom", "s", **styles)

        # channel 2 as a viewbox(overlay)
        self.p1_overlay = pg.ViewBox()
        self.p1.showAxis("right")
        self.p1.scene().addItem(self.p1_overlay)
        self.p1.getAxis("right").linkToView(self.p1_overlay)
        self.p1_overlay.setXLink(self.p1)
        self.p1.getAxis("right").setLabel("V (CH2)", **styles)

        # bottom overview window
        self.p2 = self.addPlot(row=3, col=0, rowspan=1)
        self.region = pg.LinearRegionItem()
        self.region.setZValue(10)
        self.p2.addItem(self.region)
        self.reanchor_p2_region()

        # cross hair
        self.vLine = pg.InfiniteLine(angle=90, movable=False)
        self.hLine = pg.InfiniteLine(angle=0, movable=False)
        self.p1.addItem(self.vLine, ignoreBounds=True)
        self.p1.addItem(self.hLine, ignoreBounds=True)

        # hover info label
        self.hover_info = pg.TextItem(anchor=(0.5, 0.5))
        self.hover_info.setParentItem(self.p1.vb)
        self.hover_info.setPos(35, 25)

        # set graph range
        self.p1.setXRange(
            0,
            self.controller.depth * self.controller.seconds_per_sample,
            padding=0.02,
        )
        self.p1.setYRange(-5, 5, padding=0.1)
        self.p1_overlay.setYRange(-5, 5, padding=0.1)
        self.p2.setYRange(-5, 5, padding=0.5)

        # set plot color
        self.pen_ch1 = pg.mkPen(color="r", width=3)
        self.pen_ch2 = pg.mkPen(color="g", width=3)
        self.pen_region = pg.mkPen(color="w", width=3)

        # plot data (for hover info)
        self.data_ch1 = np.zeros(self.controller.depth)
        self.data_ch2 = np.zeros(self.controller.depth)

        # plot init
        self.p1_ch1 = self.p1.plot(
            self.controller.data_time_array, self.data_ch1, pen=self.pen_ch1
        )
        self.p1_overlay.addItem(
            pg.PlotCurveItem(
                self.controller.data_time_array, self.data_ch2, pen=self.pen_ch2
            )
        )
        self.p2_ch1 = self.p2.plot(
            self.controller.data_time_array, self.data_ch1, pen=self.pen_region
        )
        self.p2_ch2 = self.p2.plot(
            self.controller.data_time_array, self.data_ch2, pen=self.pen_region
        )
        self.region.setClipItem(self.p2_ch1)
        self.region.setClipItem(self.p2_ch2)

        # update views for overlay
        self.__update_p1_overlay_views()
        self.p1.vb.sigResized.connect(self.__update_p1_overlay_views)

        # update x range with region
        self.region.sigRegionChanged.connect(self.__update_p1_xrange)

        # update region with p2
        self.p1.sigRangeChanged.connect(self.update_p2_region)

        # update crosshair and hover info
        self.p1.scene().sigMouseMoved.connect(self.__update_hover_info)

    # public methods

    def update_ch(self, x: np.ndarray, ys: list[np.ndarray]):
        # we try here because the length will be mismatch when
        # acquisition depth is changed in the middle of a run
        try:
            # plot upper window
            self.p1_ch1.setData(x, ys[0])
            self.p1_overlay.clear()
            self.p1_overlay.addItem(pg.PlotCurveItem(x, ys[1], pen=self.pen_ch2))
            # update channel data
            self.data_ch1 = ys[0]
            self.data_ch2 = ys[1]
            # plot bottom window
            self.p2_ch1.setData(x, self.data_ch1)
            self.p2_ch2.setData(x, self.data_ch2)
        except Exception:
            pass

    def update_p2_region(self, _, viewRange):
        rgn = viewRange[0]
        self.region.setRegion(rgn)

    def reanchor_p2_region(self) -> None:
        self.region.setRegion(
            [
                self.controller.data_time_array[
                    int(len(self.controller.data_time_array) * 0.25)
                ],
                self.controller.data_time_array[
                    int(len(self.controller.data_time_array) * 0.75)
                ],
            ]
        )

    def update_p2_xrange(self) -> None:
        self.p2.setXRange(
            0,
            self.controller.depth * self.controller.seconds_per_sample,
            padding=0.02,
        )

    # private methods

    def __update_p1_overlay_views(self) -> None:
        self.p1_overlay.setGeometry(self.p1.vb.sceneBoundingRect())
        self.p1_overlay.linkedViewChanged(self.p1.vb, self.p1_overlay.XAxis)

    def __update_p1_xrange(self) -> None:
        self.region.setZValue(10)
        minX, maxX = self.region.getRegion()
        self.p1.setXRange(minX, maxX, padding=0)

    def __update_hover_info(self, evt) -> None:
        pos = evt
        if self.p1.sceneBoundingRect().contains(pos):
            mousePoint = self.p1.vb.mapSceneToView(pos)
            index = int(mousePoint.x() / self.controller.seconds_per_sample)
            if 0 < index < self.controller.depth:
                # we try here because the index will be out of range when
                # acquisition depth is changed in the middle of a run
                try:
                    match self.controller.channel_enable:
                        case [True, True]:
                            self.hover_info.setHtml(
                                "<div style='background:rgba(255, 255, 255, 0.15);'><span style='font-size: 13pt;'>x=%0.2g <br> <span style='color: red;font-size:13pt;'>ch1=%0.2f</span> <br> <span style='color: green;font-size=13pt;'>ch2=%0.2f</span></div>"  # noqa: E501
                                % (
                                    mousePoint.x(),
                                    self.data_ch1[index],
                                    self.data_ch2[index],
                                )
                            )
                        case [True, False]:
                            self.hover_info.setHtml(
                                "<div style='background:rgba(255, 255, 255, 0.15);'><span style='font-size: 13pt;'>x=%0.2g <br> <span style='color: red;font-size:13pt;'>ch1=%0.2f</span></div>"  # noqa: E501
                                % (mousePoint.x(), self.data_ch1[index])
                            )
                        case [False, True]:
                            self.hover_info.setHtml(
                                "<div style='background:rgba(255, 255, 255, 0.15);'><span style='font-size: 13pt;'>x=%0.2g <br> <span style='color: green;font-size=13pt;'>ch2=%0.2f</span></div>"  # noqa: E501
                                % (mousePoint.x(), self.data_ch2[index])
                            )
                        case [False, False]:
                            pass
                except IndexError:
                    pass
            self.vLine.setPos(mousePoint.x())
            self.hLine.setPos(mousePoint.y())


class ChannelBox(QGroupBox):
    def __init__(self, title: str, controller, parent=None) -> None:
        super().__init__(title, parent=parent)
        self.controller = controller

        self.setCheckable(True)
        self.setChecked(True)

        layout = QGridLayout()
        self.setLayout(layout)

        # slider
        self.slider_hbox = QHBoxLayout()
        self.slider_vbox = QVBoxLayout()

        self.scale_slider = QSlider(orientation=Qt.Orientation.Horizontal)
        self.scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.scale_slider.setMaximum(5)
        self.scale_slider.setMinimum(1)

        self.slider_hbox.addWidget(QLabel("1", alignment=Qt.AlignLeft))  # type: ignore
        self.slider_hbox.addWidget(QLabel("5", alignment=Qt.AlignRight))  # type: ignore

        self.slider_vbox.addWidget(self.scale_slider)
        self.slider_vbox.addLayout(self.slider_hbox)
        self.slider_vbox.addStretch()
        self.slider_vbox.setSpacing(0)

        # vmax
        self.vmax_label = self.__gen_label("Vmax: ", 40)
        self.vmax_value = self.__gen_label("N/A", 45)
        self.vmax = self.__gen_hbox([self.vmax_label, self.vmax_value])

        # vmin
        self.vmin_label = self.__gen_label("Vmin: ", 40)
        self.vmin_value = self.__gen_label("N/A", 75)
        self.vmin = self.__gen_hbox([self.vmin_label, self.vmin_value])

        # Vpp
        self.vpp_label = self.__gen_label("Vpp: ", 40)
        self.vpp_value = self.__gen_label("N/A", 45)
        self.vpp = self.__gen_hbox([self.vpp_label, self.vpp_value])

        # frequency
        self.freq_label = self.__gen_label("Freq: ", 40)
        self.freq_value = self.__gen_label("N/A", 75)
        self.freq = self.__gen_hbox([self.freq_label, self.freq_value])

        layout.addWidget(QLabel("Scale"), 0, 0)
        layout.addLayout(self.slider_vbox, 0, 1)
        layout.addLayout(self.vmax, 1, 0)
        layout.addLayout(self.vmin, 1, 1)
        layout.addLayout(self.vpp, 2, 0)
        layout.addLayout(self.freq, 2, 1)

        match title:
            case "CH1":
                self.scale_slider.valueChanged.connect(self.controller.set_ch1_yrange)
                self.toggled.connect(self.controller.set_ch1_state)
            case "CH2":
                self.scale_slider.valueChanged.connect(self.controller.set_ch2_yrange)
                self.toggled.connect(self.controller.set_ch2_state)

    # private methods

    def __gen_label(self, default: str, width: int) -> QLabel:
        label = QLabel(default)
        label.setFixedWidth(width)
        return label

    def __gen_hbox(self, components: list[QLabel]) -> QHBoxLayout:
        hbox = QHBoxLayout()
        for component in components:
            hbox.addWidget(component)
        hbox.setAlignment(Qt.AlignLeft)  # type: ignore
        hbox.addStretch()
        return hbox


class TimebaseBox(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__("Timebase", parent=parent)
        self.controller = controller

        layout = QGridLayout()
        self.setLayout(layout)

        # equivalent time
        self.equiv_time = QLabel("50.00 us")

        # sample rate
        self.sample_rate_options = [
            "25 MHz",
            "12.5 MHz",
            "5 MHz",
            "2.5 MHz",
            "1.25 MHz",
            "500 kHz",
            "250 kHz",
            "125 kHz",
            "50 kHz",
            "25 kHz",
            "12.5 kHz",
            "5 kHz",
            "2.5 kHz",
            "1.25 kHz",
            "500 Hz",
        ]
        self.combobox_sample_rate = QComboBox()
        self.combobox_sample_rate.addItems(self.sample_rate_options)
        self.combobox_sample_rate.setCurrentIndex(0)

        # sample depth
        self.sample_depth_options = [
            "1250",
            "2500",
            "5000",
            "12500",
        ]
        self.combobox_sample_depth = QComboBox()
        self.combobox_sample_depth.addItems(self.sample_depth_options)
        self.combobox_sample_depth.setCurrentIndex(0)

        # equivalent time
        layout.addWidget(QLabel("Equiv. time: "), 0, 0)
        layout.addWidget(self.equiv_time, 0, 1)
        # sample rate
        layout.addWidget(QLabel("Sample rate: "), 1, 0)
        layout.addWidget(self.combobox_sample_rate, 1, 1)
        # sample depth
        layout.addWidget(QLabel("Depth(1CH): "), 2, 0)
        layout.addWidget(self.combobox_sample_depth, 2, 1)

        self.combobox_sample_rate.currentTextChanged.connect(self.__set_sample_rate)
        self.combobox_sample_depth.currentTextChanged.connect(self.__set_sample_depth)

    def __set_sample_rate(self):
        sample_rate = self.combobox_sample_rate.currentText()
        self.controller.set_sample_rate(sample_rate)

    def __set_sample_depth(self):
        sample_depth = self.combobox_sample_depth.currentText()
        self.controller.set_sample_depth(sample_depth)


class TriggerBox(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__("Trigger", parent=parent)
        self.controller = controller

        self.setCheckable(True)
        self.setChecked(False)

        layout = QGridLayout()
        self.setLayout(layout)

        # trigger channel
        self.combobox_trigger_channel = QComboBox()
        self.combobox_trigger_channel.addItems(["CH1", "CH2"])
        self.combobox_trigger_channel.setCurrentIndex(0)

        # slope
        self.combobox_slope = QComboBox()
        self.combobox_slope.addItems(["rising", "falling"])
        self.combobox_slope.setCurrentIndex(0)

        # trigger position
        self.lineedit_trigger_position = QLineEdit()
        rx_pos = QRegularExpression("^([1-9]\d{0,1}|0|100)$")  # type: ignore
        validator_pos = QRegularExpressionValidator(rx_pos)
        self.lineedit_trigger_position.setValidator(validator_pos)
        self.lineedit_trigger_position.setText("0")

        # trigger threshold
        self.lineedit_trigger_threshold = QLineEdit()
        rx_ths = QRegularExpression("^([-]{0,1})(([1-9]{1}\d*)|(0{1}))(\.\d{0,2})?$")  # type: ignore
        validator_ths = QRegularExpressionValidator(rx_ths)
        self.lineedit_trigger_threshold.setValidator(validator_ths)
        self.lineedit_trigger_threshold.setText("0.0")

        # trigger channel
        layout.addWidget(QLabel("Trigger channel"), 0, 0, 1, 2)
        layout.addWidget(self.combobox_trigger_channel, 0, 2, 1, 2)
        # slope
        layout.addWidget(QLabel("Trigger slope"), 1, 0, 1, 2)
        layout.addWidget(self.combobox_slope, 1, 2, 1, 2)
        # trigger position
        layout.addWidget(QLabel("Trigger position (%)"), 2, 0, 1, 1)
        layout.addWidget(self.lineedit_trigger_position, 2, 1, 1, 1)
        # trigger threshold
        layout.addWidget(QLabel("Trigger threshold (V)"), 2, 2, 1, 1)
        layout.addWidget(self.lineedit_trigger_threshold, 2, 3, 1, 1)

        self.toggled.connect(self.controller.set_trigger_state)
        self.combobox_slope.currentTextChanged.connect(
            self.controller.set_trigger_slope
        )
        self.combobox_trigger_channel.currentTextChanged.connect(
            self.controller.set_trigger_channel
        )
        self.lineedit_trigger_position.editingFinished.connect(
            self.__on_pos_lineedit_finished
        )
        self.lineedit_trigger_threshold.editingFinished.connect(
            self.__on_ths_lineedit_finished
        )

    def __on_pos_lineedit_finished(self):
        if int(self.lineedit_trigger_position.text()) > 100:
            self.lineedit_trigger_position.setText("100")
        elif int(self.lineedit_trigger_position.text()) < 0:
            self.lineedit_trigger_position.setText("0")
        tmp = str(
            int(
                int(self.lineedit_trigger_position.text()) / 100 * self.controller.depth
            )
        )
        self.controller.set_trigger_position(tmp)

    def __on_ths_lineedit_finished(self):
        if float(self.lineedit_trigger_threshold.text()) > 5:
            self.lineedit_trigger_threshold.setText("5.0")
        elif float(self.lineedit_trigger_threshold.text()) < -5:
            self.lineedit_trigger_threshold.setText("-5.0")
        tmp = str(int((float(self.lineedit_trigger_threshold.text()) + 5) / 10 * 255))
        self.controller.set_trigger_threshold(tmp)


class AcquisitionBox(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__("Acquisition", parent=parent)
        self.controller = controller

        self.is_running: bool = False

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.button_run = QPushButton("RUN")
        self.button_single = QPushButton("SINGLE")

        layout.addWidget(self.button_run)
        layout.addWidget(self.button_single)

        self.button_single.clicked.connect(self.on_single_button)
        self.button_run.clicked.connect(self.on_run_stop_button)

    def on_run_stop_button(self):
        if self.is_running:
            self.controller.oscilloscope_stop()
            self.is_running = False
            self.button_run.setText("RUN")
        else:
            if self.controller.oscilloscope_continuous_run():
                self.is_running = True
                self.button_run.setText("STOP")

    def on_single_button(self):
        self.controller.oscilloscope_single_run()
        self.is_running = False
        self.button_run.setText("RUN")


class UtilGraphBox(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__("Utility Graph", parent=parent)
        self.controller = controller

        self.setCheckable(True)
        self.setChecked(True)

        layout = QHBoxLayout()
        self.setLayout(layout)

        # Region button
        self.button_region = QPushButton("Reset")

        # FFT button
        self.button_fft = QPushButton("FFT")

        # graph
        layout.addWidget(self.button_region)
        layout.addWidget(self.button_fft)

        self.toggled.connect(self.controller.set_util_graph_state)
        self.button_region.clicked.connect(self.on_region_button)
        self.button_fft.clicked.connect(self.on_fft_button)

    def on_region_button(self):
        self.controller.set_util_graph_content(self.button_region.text())
        self.button_fft.setEnabled(True)
        if self.button_fft.isEnabled():
            self.button_region.setText("Reset")

    def on_fft_button(self):
        self.button_region.setText("Region")
        self.controller.set_util_graph_content("FFT")
        self.button_fft.setDisabled(True)


class StatsBox(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Stats", parent=parent)

        self.fps_label = QLabel("0 fps")

        layout = QHBoxLayout()
        self.setLayout(layout)

        layout.addWidget(QLabel("Refresh rate:"))
        layout.addWidget(self.fps_label)


class DeviceBox(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__("Device", parent=parent)
        self.controller = controller

        self.is_connected = False

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.button_connect = QPushButton("Connect")

        layout.addWidget(self.button_connect)

        self.button_connect.clicked.connect(self.connect_to_device)

    def connect_to_device(self):
        if not self.is_connected:
            self.controller.connect_device()
            self.button_connect.setText("Disconnect")
        else:
            self.controller.disconnect_device()
            self.button_connect.setText("Connect")
        # refresh status
        self.is_connected = self.controller.is_device_connected


class ControlPanel(QFrame):
    def __init__(self, controller, parent=None):
        super().__init__(parent=parent)
        self.controller = controller

        self.setFrameStyle(QFrame.StyledPanel)  # type: ignore

        self.ch1_panel = ChannelBox("CH1", self.controller)
        self.ch2_panel = ChannelBox("CH2", self.controller)
        self.time_panel = TimebaseBox(self.controller)
        self.trigger_panel = TriggerBox(self.controller)
        self.acq_panel = AcquisitionBox(self.controller)
        self.util_panel = UtilGraphBox(self.controller)
        self.stats_panel = StatsBox()
        self.dev_panel = DeviceBox(self.controller)

        layout = QGridLayout()  # type: ignore
        layout.addWidget(self.ch1_panel, 0, 0, 1, 1)
        layout.addWidget(self.ch2_panel, 0, 1, 1, 1)
        layout.addWidget(self.time_panel, 1, 0, 1, 1)
        layout.addWidget(self.acq_panel, 1, 1, 1, 1)
        layout.addWidget(self.trigger_panel, 2, 0, 1, 2)
        layout.addWidget(self.util_panel, 3, 0, 1, 2)
        layout.addWidget(self.stats_panel, 4, 0, 1, 2)
        layout.addWidget(self.dev_panel, 5, 0, 1, 2)

        self.setLayout(layout)


class MainWindow(QMainWindow):
    def __init__(self, controller, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.controller = controller

        self.setupUi()

    def setupUi(self):
        self.setWindowTitle("Lovelace")

        self.screen = OscilloscopeScreen(self.controller)
        self.screen.setMinimumSize(600, 600)
        self.control_panel = ControlPanel(self.controller)

        self.content_layout = QHBoxLayout()
        self.content_layout.addWidget(self.screen)
        self.content_layout.addWidget(self.control_panel)

        self.setCentralWidget(QWidget())
        self.centralWidget().setLayout(self.content_layout)
