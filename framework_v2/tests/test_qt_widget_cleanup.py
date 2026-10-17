import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import shiboken6
from PySide6.QtCore import QThread,QTimer
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from framework_v2.tests.qt_widget_cleanup import dispose_closed_widget

class OwnedWidgetCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_closed_window_destroys_owned_webengine_page_and_timer(self):
        window=QWidget();view=QWebEngineView(window);page=view.page();timer=QTimer(window);timer.start(20)
        destroyed=[]
        for name,obj in [('window',window),('view',view),('page',page),('timer',timer)]:
            obj.destroyed.connect(lambda *args,name=name:destroyed.append(name))
        try:
            self.assertTrue(window.close())
            self.assertTrue(all(shiboken6.isValid(x) for x in (window,view,page,timer)))
            dispose_closed_widget(window)
            self.assertFalse(any(shiboken6.isValid(x) for x in (window,view,page,timer)))
            self.assertEqual(set(destroyed),{'window','view','page','timer'})
            self.assertIs(QApplication.instance(),self.app)
        finally:
            if shiboken6.isValid(window):window.close();dispose_closed_widget(window)

    def test_visible_window_is_preserved(self):
        window=QWidget();window.show();self.app.processEvents()
        try:
            with self.assertRaisesRegex(RuntimeError,'close was rejected'):dispose_closed_widget(window)
            self.assertTrue(shiboken6.isValid(window));self.assertTrue(window.isVisible())
        finally:window.close();dispose_closed_widget(window)

    def test_running_owned_thread_is_preserved(self):
        window=QWidget();thread=QThread(window);thread.start()
        try:
            self.assertTrue(window.close());self.assertTrue(thread.isRunning())
            with self.assertRaisesRegex(RuntimeError,'running owned QThread'):dispose_closed_widget(window)
            self.assertTrue(shiboken6.isValid(window));self.assertTrue(thread.isRunning())
        finally:
            thread.quit();self.assertTrue(thread.wait(5000));dispose_closed_widget(window)

if __name__=='__main__':unittest.main(verbosity=2)
