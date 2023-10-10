from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QMainWindow,
    QPushButton,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QGridLayout,
    QSlider,
    QGroupBox,
    QLabel,
)
from PySide6.QtCore import Qt
import pyqtgraph as pg


class OscilloscopeScreen(pg.PlotWidget):
    def __init__(self, parent=None, plotItem=None, **kargs):
        super().__init__(parent=parent, background="w", plotItem=plotItem, **kargs)

        styles = {"color": "k", "font-size": "12px"}

        self.setLabel("left", "V (CH1)", **styles)
        self.setLabel("bottom", "s", **styles)

        # channel 2 as a viewbox(overlay)
        self.overlay = pg.ViewBox()
        self.plotItem.showAxis("right")  # type: ignore
        self.plotItem.scene().addItem(self.overlay)  # type: ignore
        self.plotItem.getAxis("right").linkToView(self.overlay)  # type: ignore
        self.overlay.setXLink(self.plotItem)
        self.plotItem.getAxis("right").setLabel("V (CH2)", **styles)  # type: ignore

        # label
        self.label = pg.LabelItem(justify="right", color="#ffffff")
        self.label.setText("TEXT")
        self.overlay.addItem(self.label)

        # set graph range
        self.setXRange(0, 1, padding=0.02)  # type: ignore
        self.setYRange(-5, 5, padding=0.02)  # type: ignore
        self.overlay.setYRange(-5, 5, padding=0.02)  # type: ignore

        # set plot color
        self.pen_ch1 = pg.mkPen(color="b", width=3)
        self.pen_ch2 = pg.mkPen(color="r", width=3)

        # plot init
        self.data_line_ch1 = self.plot([0, 1], [0, 0], pen=self.pen_ch1)
        self.overlay.addItem(pg.PlotCurveItem([0, 1], [0, 0], pen=self.pen_ch2))

        # update views for overlay
        self.update_views()
        self.plotItem.vb.sigResized.connect(self.update_views)  # type: ignore

    def update_ch(self, x, ys):
        self.data_line_ch1.setData(x, ys[0])
        self.overlay.clear()
        self.overlay.addItem(pg.PlotCurveItem(x, ys[1], pen=self.pen_ch2))

    def update_views(self):
        self.overlay.setGeometry(self.plotItem.vb.sceneBoundingRect())  # type: ignore
        self.overlay.linkedViewChanged(self.plotItem.vb, self.overlay.XAxis)  # type: ignore


class ChannelBox(QGroupBox):
    def __init__(self, title: str, controller, parent=None):
        super().__init__(title, parent=parent)
        self.controller = controller

        self.setCheckable(True)
        self.setChecked(True)

        layout = QGridLayout()
        self.slider_hbox = QHBoxLayout()
        self.slider_vbox = QVBoxLayout()
        self.setLayout(layout)

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

        layout.addWidget(QLabel("Scale"), 0, 0)
        layout.addLayout(self.slider_vbox, 0, 1)

        match title:
            case "CH1":
                self.scale_slider.valueChanged.connect(self.controller.set_ch1_yrange)
            case "CH2":
                self.scale_slider.valueChanged.connect(self.controller.set_ch2_yrange)


class TimebaseBox(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__("Timebase", parent=parent)
        self.controller = controller

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.timebase_options = [
            "1 us",
            "2 us",
            "5 us",
            "10 us",
            "20 us",
            "50 us",
            "100 us",
            "200 us",
            "500 us",
            "1 ms",
            "2 ms",
            "5 ms",
            "10 ms",
            "20 ms",
            "50 ms",
        ]
        self.combobox_timebase = QComboBox()
        self.combobox_timebase.addItems(self.timebase_options)
        self.combobox_timebase.setCurrentIndex(0)

        layout.addWidget(QLabel("time/div (1 div = 1/10 graph)"))
        layout.addWidget(self.combobox_timebase)

        self.combobox_timebase.currentTextChanged.connect(self.set_timebase)

    def set_timebase(self):
        timebase = self.combobox_timebase.currentText()
        self.controller.set_timebase(timebase)


class TriggerBox(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__("Trigger", parent=parent)
        self.controller = controller

        self.setCheckable(True)
        self.setChecked(False)

        layout = QHBoxLayout()
        self.setLayout(layout)

        self.combobox_slope = QComboBox()
        self.combobox_slope.addItems(["rising", "falling"])
        self.combobox_slope.setCurrentIndex(0)

        layout.addWidget(QLabel("Trigger slope"))
        layout.addWidget(self.combobox_slope)

        self.toggled.connect(self.controller.set_trigger_state)
        self.combobox_slope.currentTextChanged.connect(
            self.controller.set_trigger_slope
        )


class AcquisitionBox(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__("Acquisition", parent=parent)
        self.controller = controller

        self.is_running = False

        layout = QHBoxLayout()
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

        self.button_refresh = QPushButton("Refresh")
        self.combobox_ports = QComboBox()
        self.button_connect = QPushButton("Connect")

        layout.addWidget(self.button_refresh)
        layout.addWidget(self.combobox_ports)
        layout.addWidget(self.button_connect)

        self.button_refresh.clicked.connect(self.refresh_ports)
        self.button_connect.clicked.connect(self.connect_to_device)

    def refresh_ports(self):
        self.combobox_ports.clear()
        self.combobox_ports.addItems(self.controller.get_ports_names())

    def connect_to_device(self):
        if not self.is_connected:
            port = self.combobox_ports.currentText()
            self.controller.connect_device(port)
        else:
            self.controller.disconnect_device()

        self.is_connected = self.controller.is_device_connected
        if self.is_connected:
            self.button_connect.setText("Disconnect")
        else:
            self.button_connect.setText("Connect")


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
        self.stats_panel = StatsBox()
        self.dev_panel = DeviceBox(self.controller)

        self.layout = QVBoxLayout()  # type: ignore
        self.layout.addWidget(self.ch1_panel)
        self.layout.addWidget(self.ch2_panel)
        self.layout.addWidget(self.time_panel)
        self.layout.addWidget(self.trigger_panel)
        self.layout.addWidget(self.acq_panel)
        self.layout.addWidget(self.stats_panel)
        self.layout.addStretch()
        self.layout.addWidget(self.dev_panel)

        self.setLayout(self.layout)


class MainWindow(QMainWindow):
    def __init__(self, controller, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.controller = controller

        self.setupUi()

    def setupUi(self):
        self.setWindowTitle("Lovelace")

        self.screen = OscilloscopeScreen()
        self.control_panel = ControlPanel(self.controller)

        self.content_layout = QHBoxLayout()
        self.content_layout.addWidget(self.screen)
        self.content_layout.addWidget(self.control_panel)

        self.setCentralWidget(QWidget())
        self.centralWidget().setLayout(self.content_layout)
