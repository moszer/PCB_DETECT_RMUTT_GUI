"""Reusable animation helpers for a production-grade feel.

Qt stylesheets can't animate, so every transition lives here as a
QPropertyAnimation / QVariantAnimation. Helpers keep a reference to the
running animation on the target widget so it survives garbage collection.
"""
from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QVariantAnimation,
    pyqtProperty,
    QObject,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QGraphicsDropShadowEffect


def fade_in(widget, duration=280, start=0.0, end=1.0, on_finished=None, clear_effect=True):
    """Fade a widget's opacity. Removes the effect when done so painting stays crisp."""
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _done():
        if clear_effect:
            widget.setGraphicsEffect(None)
        if on_finished:
            on_finished()

    anim.finished.connect(_done)
    widget._fade_anim = anim
    anim.start()
    return anim


def pulse_glow(widget, color, blur=46, cycles=2, duration=1500, on_finished=None):
    """Pulse a coloured glow around a widget (used to draw the eye to a FAIL)."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setOffset(0, 0)
    shadow.setColor(QColor(color))
    shadow.setBlurRadius(0)
    widget.setGraphicsEffect(shadow)

    anim = QPropertyAnimation(shadow, b"blurRadius", widget)
    anim.setDuration(duration)
    anim.setStartValue(0)
    anim.setKeyValueAt(0.5, blur)
    anim.setEndValue(0)
    anim.setEasingCurve(QEasingCurve.Type.InOutSine)
    anim.setLoopCount(cycles)

    def _done():
        widget.setGraphicsEffect(None)
        if on_finished:
            on_finished()

    anim.finished.connect(_done)
    widget._glow_anim = anim
    anim.start()
    return anim


def reveal_then_glow(widget, glow_color=None, duration=260):
    """Fade a widget in; optionally follow with a glow pulse afterwards."""

    def _after():
        if glow_color is not None:
            pulse_glow(widget, glow_color)

    fade_in(widget, duration=duration, on_finished=_after)


def animate_number(label, end_value, fmt="{}", duration=520, start_value=None):
    """Tween an integer displayed in a QLabel from its current value to end_value."""
    if start_value is None:
        start_value = getattr(label, "_num_value", 0)
    start_value = int(start_value)
    end_value = int(end_value)
    label._num_value = end_value

    if start_value == end_value:
        label.setText(fmt.format(end_value))
        return None

    anim = QVariantAnimation(label)
    anim.setStartValue(start_value)
    anim.setEndValue(end_value)
    anim.setDuration(duration)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.valueChanged.connect(lambda v: label.setText(fmt.format(int(v))))
    anim.finished.connect(lambda: label.setText(fmt.format(end_value)))
    label._num_anim = anim
    anim.start()
    return anim


class _BarValue(QObject):
    """Wrapper exposing an animatable float that redraws a progress bar."""

    def __init__(self, apply_fn):
        super().__init__()
        self._value = 0.0
        self._apply = apply_fn

    def get_value(self):
        return self._value

    def set_value(self, v):
        self._value = v
        self._apply(v)

    value = pyqtProperty(float, fget=get_value, fset=set_value)


def animate_bar(holder_attr_owner, attr_name, apply_fn, end_ratio, duration=560):
    """Animate a 0..1 ratio, calling apply_fn(ratio) each step. Keeps the wrapper alive."""
    wrapper = getattr(holder_attr_owner, attr_name, None)
    if wrapper is None:
        wrapper = _BarValue(apply_fn)
        setattr(holder_attr_owner, attr_name, wrapper)
    else:
        wrapper._apply = apply_fn

    start = wrapper.get_value()
    end_ratio = max(0.0, min(1.0, float(end_ratio)))
    anim = QPropertyAnimation(wrapper, b"value", wrapper)
    anim.setDuration(duration)
    anim.setStartValue(start)
    anim.setEndValue(end_ratio)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    wrapper._anim = anim
    anim.start()
    return anim
