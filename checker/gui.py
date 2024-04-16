import sys, maths, logic

use_qt5 = True
if not "--qt5" in sys.argv:
    use_qt5 = False
    try:
        from PyQt6 import uic
        from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox
    except ImportError:
        use_qt5 = True
if use_qt5:
    from PyQt5 import uic
    from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox

class MainWindow(QMainWindow):
    def compare(self):
        expr_target = self.le_target.text()
        expr_test = self.le_test.text()
        result = maths.check(expr_target, expr_test, _quiet=True)
        msg = QMessageBox()
        if 'error' in result:
            msg.setWindowTitle("Error!")
            msg.setText(result['error'])
            msg.setIcon(QMessageBox.Icon.Warning)
        elif 'equal' in result:
            if 'equality_type' in result:
                equality = result['equality_type']
            else:
                equality = "Unknown type of"
            if result['equal'] == 'true':
                msg.setWindowTitle("Done!")
                msg.setText(f"Equal ({equality} equality)")
                msg.setIcon(QMessageBox.Icon.Information)
            else:
                msg.setWindowTitle("Done!")
                msg.setText(f"Not equal ({equality} inequality)")
                msg.setIcon(QMessageBox.Icon.Information)
        else:
            msg.setWindowTitle("Error!")
            msg.setText(f"Got unexpected response from check():\n{result}")
            msg.setIcon(QMessageBox.Icon.Critical)
        msg.exec()

    def __init__(self):
        super().__init__()
        uic.loadUi("./pyqt.ui", self)
        self.btn_check.clicked.connect(self.compare)
        self.show()

app = QApplication(sys.argv)
window = MainWindow()
app.exec()
exit(0)
