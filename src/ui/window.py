import sys
from pathlib import Path
from src.utils.logger import get_logger

logger = get_logger("ui.window")

# Delay imports of PySide6 until start_ui, or try block
try:
    from PySide6.QtCore import Qt, QUrl, QObject, Signal, Slot
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtWebEngineWidgets import QWebEngineView
    PYSIDE_AVAILABLE = True
except ImportError:
    PYSIDE_AVAILABLE = False

if PYSIDE_AVAILABLE:
    class SignalBridge(QObject):
        state_changed = Signal(str)
        level_changed = Signal(float)
else:
    SignalBridge = object

logger = get_logger("ui.window")

class UIController:
    def __init__(self):
        self.app = None
        self.window = None
        self.view = None
        self.bridge = None

    def start_ui(self):
        if not PYSIDE_AVAILABLE:
            logger.error("PySide6 is not installed. Please wait for the installation to finish.")
            return

        self.bridge = SignalBridge()
        self.bridge.state_changed.connect(self._do_set_state)
        self.bridge.level_changed.connect(self._do_set_level)

        if not QApplication.instance():
            self.app = QApplication(sys.argv)
        else:
            self.app = QApplication.instance()

        self.window = QMainWindow()
        
        # Qt.Tool hides it from the taskbar. FramelessWindowHint removes the title bar.
        # WindowTransparentForInput makes it "click-through" so you can interact with windows behind it!
        self.window.setWindowFlags(
            Qt.FramelessWindowHint | 
            Qt.WindowStaysOnTopHint | 
            Qt.Tool | 
            Qt.WindowTransparentForInput
        )
        
        # This enables true OS-level transparency (no black boxes!)
        self.window.setAttribute(Qt.WA_TranslucentBackground, True)
        
        # Sizing (smaller so it's less intrusive)
        self.window.resize(350, 350)
        
        # Position it elegantly in the bottom right corner of the screen
        screen = self.app.primaryScreen().availableGeometry()
        self.window.move(screen.width() - 370, screen.height() - 370)
        
        self.view = QWebEngineView(self.window)
        # Force Chromium to render transparently
        self.view.page().setBackgroundColor(Qt.transparent)
        
        html_path = Path("ui/index.html").absolute()
        logger.info(f"Loading UI from {html_path}")
        self.view.setUrl(QUrl.fromLocalFile(str(html_path)))
        
        self.window.setCentralWidget(self.view)
        self.window.show()
        
        # This blocks the main thread
        self.app.exec()

    def set_state(self, state: str):
        """Update the Orb state safely from any thread"""
        if self.bridge:
            self.bridge.state_changed.emit(state)

    def set_level(self, level: float):
        """Update the audio level safely from any thread"""
        if self.bridge:
            self.bridge.level_changed.emit(level)

    @Slot(str)
    def _do_set_state(self, state: str):
        if self.view:
            try:
                self.view.page().runJavaScript(f"if (window.AgentOrb) window.AgentOrb.set('{state}')")
            except Exception as e:
                logger.error(f"Failed to update UI state: {e}")

    @Slot(float)
    def _do_set_level(self, level: float):
        if self.view:
            try:
                self.view.page().runJavaScript(f"if (window.AgentOrb) window.AgentOrb.setLevel({level})")
            except Exception as e:
                pass
