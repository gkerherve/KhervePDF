"""Slideshow: whole-page presentation, windowed or full screen, manual
or continuous — plus its integration with the main window."""
import fitz
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolBar

from khervepdf.mainwindow import MainWindow
from khervepdf.pdftab import Annotation, PdfTab
from khervepdf.slideshow import SlideshowView


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _make_pdf(path, pages=4):
    doc = fitz.open()
    for i in range(pages):
        p = doc.new_page()
        p.insert_text((72, 120), f"Page {i + 1}", fontsize=30)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture()
def pdf(tmp_path):
    return _make_pdf(tmp_path / "deck.pdf")


@pytest.fixture()
def view(app, pdf):
    v = SlideshowView(fitz.open(str(pdf)), 0, loop=False)
    v.resize(800, 600)
    v.show()
    yield v
    v.dispose()
    v.close()


# ---- the stage ----------------------------------------------------------

def test_start_page_is_clamped(app, pdf):
    v = SlideshowView(fitz.open(str(pdf)), 99)
    assert v.current_page() == 3
    v.dispose()


def test_keys_flip_pages_and_do_not_scroll(view):
    QTest.keyClick(view, Qt.Key_Right)
    QTest.keyClick(view, Qt.Key_Space)
    assert view.current_page() == 2
    QTest.keyClick(view, Qt.Key_Left)
    assert view.current_page() == 1
    QTest.keyClick(view, Qt.Key_End)
    assert view.current_page() == 3
    QTest.keyClick(view, Qt.Key_Home)
    assert view.current_page() == 0


def test_no_wrap_without_loop(view):
    view.goto(3)
    view.next_page()
    assert view.current_page() == 3
    view.goto(0)
    view.prev_page()
    assert view.current_page() == 0


def test_loop_wraps_both_ways(view):
    view.set_loop(True)
    view.goto(3)
    view.next_page()
    assert view.current_page() == 0
    view.prev_page()
    assert view.current_page() == 3


def test_escape_and_mode_keys_emit(view):
    got = []
    view.exit_requested.connect(lambda: got.append("exit"))
    view.mode_switch_requested.connect(lambda: got.append("mode"))
    QTest.keyClick(view, Qt.Key_F)
    QTest.keyClick(view, Qt.Key_Escape)
    assert got == ["mode", "exit"]


def test_whole_page_is_fitted_inside_the_stage(view):
    pm = view._pixmap_for(0)
    dpr = pm.devicePixelRatio()
    w, h = pm.width() / dpr, pm.height() / dpr
    assert w <= view.width() + 1 and h <= view.height() + 1
    # A4-ish portrait page in a landscape stage is limited by height.
    assert abs(h - view.height()) <= 1


def test_continuous_advances_on_its_own(app, pdf):
    v = SlideshowView(fitz.open(str(pdf)), 0, continuous=True, loop=True)
    v.resize(400, 300)
    v.show()
    v._interval_ms = 150
    QTest.qWait(500)
    assert v.current_page() >= 2
    v.dispose()


def test_continuous_stops_on_last_page_without_loop(app, pdf):
    v = SlideshowView(fitz.open(str(pdf)), 2, continuous=True, loop=False)
    v.resize(400, 300)
    v.show()
    v._interval_ms = 100
    seen = []
    v.settings_changed.connect(lambda c, s, l: seen.append(c))
    QTest.qWait(600)
    assert v.current_page() == 3
    assert not v.is_continuous()
    assert seen == [False]      # the host is told auto-advance switched off
    v.dispose()


def test_pausing_keeps_the_page(app, pdf):
    v = SlideshowView(fitz.open(str(pdf)), 0, continuous=True, loop=True)
    v.resize(400, 300)
    v.show()
    v._interval_ms = 100
    v.set_continuous(False)
    QTest.qWait(400)
    assert v.current_page() == 0
    v.dispose()


def test_interval_is_clamped(view):
    view.set_interval(0)
    assert view.interval_seconds() == 1
    view.set_interval(10_000)
    assert view.interval_seconds() == 600


def test_dispose_closes_the_document_and_is_idempotent(app, pdf):
    doc = fitz.open(str(pdf))
    v = SlideshowView(doc, 0)
    v.dispose()
    v.dispose()
    assert doc.is_closed


# ---- baked annotations --------------------------------------------------

def test_slideshow_copy_contains_unsaved_annotations(app, pdf):
    tab = PdfTab(pdf)
    tab._annots.append(Annotation(
        type="rect", page_idx=0, color="#ff0000", width=2.0,
        pts=[(100.0, 200.0), (200.0, 260.0)]))
    copy = tab.slideshow_document()
    try:
        assert len(list(copy[0].annots())) == 1
        # The tab's own document is untouched (still unsaved/in memory).
        assert len(list(tab._doc[0].annots())) == 0
        assert len(tab._annots) == 1
    finally:
        copy.close()
        tab.close_doc()


# ---- main window --------------------------------------------------------

@pytest.fixture()
def win(app, pdf):
    QSettings("kherve", "KhervePDF").clear()    # isolated by conftest
    w = MainWindow("Light")
    w.resize(1000, 700)
    w.show()
    yield w
    if w._slideshow is not None:
        w._end_slideshow()
    w.close()


def test_slideshow_actions_need_an_open_pdf(win, pdf):
    assert not win._act_show_full.isEnabled()
    win.open_path(pdf)
    assert win._act_show_full.isEnabled()
    assert win._act_show_window.isEnabled()


def test_windowed_show_takes_the_window_and_gives_it_back(win, pdf):
    win.open_path(pdf)
    toolbar = win.findChildren(QToolBar, options=Qt.FindDirectChildrenOnly)[0]
    assert toolbar.isVisible()
    win._act_show_window.trigger()
    sv = win._slideshow
    assert sv is not None and not sv.isWindow()
    assert win._central.currentWidget() is sv
    assert not toolbar.isVisible()
    assert win._act_show_window.isChecked()
    QTest.keyClick(sv, Qt.Key_Right)
    assert "2 of 4" in win._lbl_page.text()
    QTest.keyClick(sv, Qt.Key_Escape)
    assert win._slideshow is None
    assert win._central.currentWidget() is win._tabs
    assert toolbar.isVisible()
    assert win._act_normal.isChecked()


def test_fullscreen_show_is_its_own_window(win, pdf):
    win.open_path(pdf)
    win._act_show_full.trigger()
    sv = win._slideshow
    assert sv.isWindow() and sv.isFullScreen()
    assert win._central.currentWidget() is win._tabs    # main window untouched
    win._act_show_full.trigger()                        # active view again = leave
    assert win._slideshow is None


def test_switching_mode_keeps_the_page(win, pdf):
    win.open_path(pdf)
    win._act_show_window.trigger()
    win._slideshow.goto(2)
    QTest.keyClick(win._slideshow, Qt.Key_F)
    assert win._slideshow_full
    assert win._slideshow.current_page() == 2


def test_continuous_setting_reaches_the_show_and_is_remembered(win, pdf):
    win.open_path(pdf)
    win._act_continuous.setChecked(True)
    win._slide_interval.setValue(7)
    win._act_show_window.trigger()
    assert win._slideshow.is_continuous()
    assert win._slideshow.interval_seconds() == 7
    # Pausing from the on-stage bar is mirrored in the status bar.
    win._slideshow.set_continuous(False)
    assert not win._act_continuous.isChecked()
    s = QSettings("kherve", "KhervePDF")
    assert str(s.value("slideshow/continuous")).lower() == "false"
    assert int(s.value("slideshow/interval")) == 7


def test_closing_the_tab_ends_the_show(win, pdf):
    win.open_path(pdf)
    win._act_show_window.trigger()
    win._close_tab(0)
    assert win._slideshow is None
    assert win.is_welcome_visible()
    assert not win._act_show_full.isEnabled()


def test_windowed_show_does_not_persist_the_hidden_ai_dock(win, pdf):
    win.open_path(pdf)
    win._ai_dock.show()
    s = QSettings("kherve", "KhervePDF")
    assert str(s.value("ai/visible")).lower() == "true"
    win._act_show_window.trigger()
    assert str(s.value("ai/visible")).lower() == "true"   # still the user's choice
    win._end_slideshow()
    assert win._ai_dock.isVisible()


def test_icons_share_one_colour_and_follow_the_theme(win):
    from khervepdf import icons
    light = icons.DEFAULT_COLOR
    win._set_theme("Dracula")
    assert icons.DEFAULT_COLOR != light
    # Whatever the theme, every named icon is drawn in that one colour.
    assert not hasattr(icons, "_COLORS_LIGHT")
