# -*- coding: utf-8 -*-
"""主题预设、自定义颜色和圆形 HSV 调色盘。"""
import colorsys
import math

from PySide6.QtCore import Qt, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from theme import (
    C, DEFAULT_THEME_ID, EDITABLE_COLOR_KEYS, PRESET_BY_ID, THEME_FIELDS,
    THEME_PRESETS, best_text_color, normalize_hex_color, preset_colors,
    resolve_theme,
)


ACCENT_RECOMMENDATIONS = (
    "#2563EB", "#22A7F0", "#21B8B2", "#2FBF71", "#D4A72C", "#F08C32",
    "#E05275", "#D946EF", "#9B7BEA", "#7C5CE7", "#64748B", "#E8E8EA",
)
BACKGROUND_RECOMMENDATIONS = (
    "#0C0C0B", "#11151A", "#171719", "#1E1F22", "#243034", "#302429",
    "#E8ECF0", "#F3F5F7", "#F8FAFC", "#FFFFFF", "#EAF2EF", "#F6EDF0",
)
TEXT_RECOMMENDATIONS = (
    "#FFFFFF", "#F4ECD8", "#EDF4F7", "#F7EDEF", "#E8E8EA", "#B7C0C8",
    "#9A9CA1", "#667085", "#475467", "#30343A", "#20242A", "#101114",
)


def _rgb(value):
    value = normalize_hex_color(value)
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def color_swatch_icon(color, size=22, border=None):
    """生成圆形色样，供颜色项和推荐色复用。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor(normalize_hex_color(color)))
    painter.setPen(QPen(QColor(border or C["border"]), 1))
    painter.drawEllipse(QRectF(1.5, 1.5, size - 3, size - 3))
    painter.end()
    return QIcon(pm)


def preset_icon(colors, width=68, height=30):
    """一张小型界面色卡，比单个色点更能表达预设整体效果。"""
    c = resolve_theme(colors)
    pm = QPixmap(width, height)
    pm.fill(QColor(c["bg"]))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(c["bg_side"]))
    painter.drawRect(QRectF(0, 0, width * 0.27, height))
    painter.setBrush(QColor(c["card"]))
    painter.drawRoundedRect(QRectF(width * 0.34, 4, width * 0.58, height - 8), 3, 3)
    painter.setBrush(QColor(c["accent"]))
    painter.drawRoundedRect(QRectF(width * 0.44, height - 10, width * 0.36, 5), 2, 2)
    painter.setBrush(QColor(c["text"]))
    painter.drawRoundedRect(QRectF(width * 0.39, 8, width * 0.34, 3), 1.5, 1.5)
    painter.setBrush(QColor(c["ok"]))
    painter.drawEllipse(QRectF(5, 6, 5, 5))
    painter.setBrush(QColor(c["warn"]))
    painter.drawEllipse(QRectF(5, 14, 5, 5))
    painter.setBrush(QColor(c["err"]))
    painter.drawEllipse(QRectF(5, 22, 5, 5))
    painter.end()
    return QIcon(pm)


def palette_icon(size=30, side_color=None):
    """彩色画家调色盘图标，用在左下角主题入口。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor(C["border"]), 1))
    painter.setBrush(QColor(C["text"]))
    painter.drawEllipse(QRectF(2, 3, size - 4, size - 7))

    # 用侧栏颜色画出拇指孔。主题切换后图标会重建，因此孔始终自然融入背景。
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(side_color or C["bg_side"]))
    painter.drawEllipse(QRectF(size * 0.62, size * 0.55,
                               size * 0.22, size * 0.22))
    swatches = ((0.28, 0.31, "#F05D58"), (0.50, 0.22, "#D6A72B"),
                (0.68, 0.32, "#2FBF71"), (0.35, 0.57, "#4A9EFF"))
    for x, y, color in swatches:
        painter.setBrush(QColor(color))
        d = size * 0.15
        painter.drawEllipse(QRectF(size * x - d / 2, size * y - d / 2, d, d))
    painter.end()
    return QIcon(pm)


class ColorWheel(QWidget):
    """圆形 HSV 调色盘：角度选色相，半径选饱和度，滑条控制亮度。"""
    colorChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0.58
        self._saturation = 0.70
        self._value = 1.0
        self._cache_key = None
        self._cache = None
        self.setMinimumSize(218, 218)
        self.setMaximumSize(250, 250)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName("圆形全色调色盘")

    def sizeHint(self):
        return QSize(232, 232)

    def _geometry(self):
        diameter = max(20.0, min(self.width(), self.height()) - 16.0)
        return ((self.width() - diameter) / 2.0,
                (self.height() - diameter) / 2.0, diameter)

    def color(self):
        r, g, b = colorsys.hsv_to_rgb(
            self._hue, self._saturation, self._value)
        return "#{:02X}{:02X}{:02X}".format(
            round(r * 255), round(g * 255), round(b * 255))

    def setColor(self, color):
        r, g, b = (v / 255.0 for v in _rgb(color))
        hue, saturation, value = colorsys.rgb_to_hsv(r, g, b)
        self._hue = hue if saturation > 0.0001 else self._hue
        self._saturation = saturation
        self._value = value
        self._cache_key = None
        self.update()

    def setValue(self, value, emit=True):
        value = max(0.0, min(1.0, float(value)))
        if abs(value - self._value) < 0.0001:
            return
        self._value = value
        self.update()
        if emit:
            self.colorChanged.emit(self.color())

    def value(self):
        return self._value

    def _wheel_image(self):
        width, height = max(1, self.width()), max(1, self.height())
        key = (width, height)
        if key == self._cache_key and self._cache is not None:
            return self._cache
        image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        left, top, diameter = self._geometry()
        radius = diameter / 2.0
        cx, cy = left + radius, top + radius
        for y in range(max(0, int(top)), min(height, int(top + diameter) + 1)):
            dy = cy - (y + 0.5)
            for x in range(max(0, int(left)), min(width, int(left + diameter) + 1)):
                dx = (x + 0.5) - cx
                saturation = math.hypot(dx, dy) / radius
                if saturation > 1.0:
                    continue
                hue = (math.atan2(dy, dx) / (2.0 * math.pi)) % 1.0
                r, g, b = colorsys.hsv_to_rgb(hue, saturation, 1.0)
                image.setPixelColor(x, y, QColor(
                    round(r * 255), round(g * 255), round(b * 255)))
        self._cache_key, self._cache = key, image
        return image

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawImage(0, 0, self._wheel_image())
        left, top, diameter = self._geometry()
        if self._value < 0.999:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, round((1.0 - self._value) * 255)))
            painter.drawEllipse(QRectF(left, top, diameter, diameter))
        radius = diameter / 2.0
        cx, cy = left + radius, top + radius
        angle = self._hue * 2.0 * math.pi
        x = cx + math.cos(angle) * self._saturation * radius
        y = cy - math.sin(angle) * self._saturation * radius
        marker = best_text_color(self.color())
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(marker), 2))
        painter.drawEllipse(QRectF(x - 6, y - 6, 12, 12))
        painter.setPen(QPen(QColor(C["border"]), 1))
        painter.drawEllipse(QRectF(left, top, diameter, diameter))
        painter.end()

    def _pick(self, position):
        left, top, diameter = self._geometry()
        radius = diameter / 2.0
        cx, cy = left + radius, top + radius
        dx, dy = position.x() - cx, cy - position.y()
        distance = math.hypot(dx, dy)
        if distance > radius + 8:
            return False
        self._hue = (math.atan2(dy, dx) / (2.0 * math.pi)) % 1.0
        self._saturation = min(1.0, distance / radius)
        self.update()
        self.colorChanged.emit(self.color())
        return True

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.position())

    def keyPressEvent(self, event):
        handled = True
        if event.key() == Qt.Key_Left:
            self._hue = (self._hue - 1 / 180.0) % 1.0
        elif event.key() == Qt.Key_Right:
            self._hue = (self._hue + 1 / 180.0) % 1.0
        elif event.key() == Qt.Key_Up:
            self._saturation = min(1.0, self._saturation + 0.02)
        elif event.key() == Qt.Key_Down:
            self._saturation = max(0.0, self._saturation - 0.02)
        else:
            handled = False
        if handled:
            self.update()
            self.colorChanged.emit(self.color())
            event.accept()
        else:
            super().keyPressEvent(event)


class ThemePreview(QWidget):
    """不依赖全局 QSS 的实时主题缩略图。"""
    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self._colors = resolve_theme(colors)
        self.setObjectName("ThemePreview")
        self.setMinimumHeight(152)
        self.setAccessibleName("当前配色预览")

    def setColors(self, colors):
        self._colors = resolve_theme(colors)
        self.update()

    def paintEvent(self, _event):
        c = self._colors
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["bg"]))
        p.drawRoundedRect(box, 7, 7)
        side_w = max(62, round(box.width() * 0.27))
        p.setBrush(QColor(c["bg_side"]))
        p.drawRoundedRect(QRectF(box.left(), box.top(), side_w, box.height()), 7, 7)
        p.drawRect(QRectF(box.left() + side_w - 7, box.top(), 7, box.height()))
        p.setBrush(QColor(c["text"]))
        p.drawRoundedRect(QRectF(14, 16, side_w - 27, 5), 2, 2)
        p.setBrush(QColor(c["accent"]))
        p.drawRoundedRect(QRectF(10, 45, side_w - 20, 25), 4, 4)
        p.setBrush(QColor(c["accent_text"]))
        p.drawRoundedRect(QRectF(20, 55, side_w - 40, 4), 2, 2)

        main_x = side_w + 14
        p.setBrush(QColor(c["text"]))
        p.drawRoundedRect(QRectF(main_x, 16, min(110, box.width() - main_x - 18), 6), 3, 3)
        p.setBrush(QColor(c["card"]))
        p.drawRoundedRect(QRectF(main_x, 34, box.width() - main_x - 14,
                                 box.height() - 48), 6, 6)
        p.setBrush(QColor(c["input"]))
        p.drawRoundedRect(QRectF(main_x + 11, 48, box.width() - main_x - 36, 24), 4, 4)
        p.setBrush(QColor(c["text_dim"]))
        p.drawRoundedRect(QRectF(main_x + 19, 58,
                                 min(94, box.width() - main_x - 52), 4), 2, 2)
        button_w = max(70, (box.width() - main_x - 47) / 2)
        p.setBrush(QColor(c["accent"]))
        p.drawRoundedRect(QRectF(main_x + 11, 84, button_w, 26), 4, 4)
        p.setBrush(QColor(c["accent_text"]))
        p.drawRoundedRect(QRectF(main_x + 25, 95, button_w - 28, 4), 2, 2)
        for index, name in enumerate(("ok", "warn", "err")):
            p.setBrush(QColor(c[name]))
            p.drawEllipse(QRectF(main_x + 16 + index * 24, 123, 10, 10))
        p.end()


class ThemeSettingsDialog(QDialog):
    def __init__(self, preset_id=DEFAULT_THEME_ID, colors=None, parent=None):
        super().__init__(parent)
        if preset_id in PRESET_BY_ID:
            initial = preset_colors(preset_id)
            if isinstance(colors, dict):
                initial.update({key: normalize_hex_color(colors.get(key), initial[key])
                                for key in EDITABLE_COLOR_KEYS if key in colors})
        else:
            initial = preset_colors(DEFAULT_THEME_ID)
            if isinstance(colors, dict):
                initial.update({key: normalize_hex_color(colors.get(key), initial[key])
                                for key in EDITABLE_COLOR_KEYS if key in colors})
            preset_id = "custom"
        self._colors = initial
        self._preset_id = preset_id
        self._field = "accent"
        self._syncing = False
        self._preset_buttons = {}
        self._field_buttons = {}
        self._recommend_buttons = []

        self.setWindowTitle("界面配色")
        self.setModal(True)
        self.setMinimumSize(900, 630)
        self.resize(960, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        title_row = QHBoxLayout()
        title = QLabel("界面配色")
        title.setObjectName("PageTitle")
        self.badge = QLabel("")
        self.badge.setObjectName("ThemeCustomBadge")
        title_row.addWidget(title)
        title_row.addWidget(self.badge)
        title_row.addStretch(1)
        root.addLayout(title_row)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body, 1)

        left = QFrame()
        left.setObjectName("ThemePickerPanel")
        left.setMinimumWidth(360)
        left.setMaximumWidth(390)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 14, 16, 16)
        ll.setSpacing(10)
        heading = QLabel("一键主题")
        heading.setObjectName("CardTitle")
        ll.addWidget(heading)
        preset_grid = QGridLayout()
        preset_grid.setSpacing(8)
        self._preset_group = QButtonGroup(self)
        self._preset_group.setExclusive(True)
        for index, preset in enumerate(THEME_PRESETS):
            button = QPushButton(preset["name"])
            button.setObjectName("ThemePresetButton")
            button.setCheckable(True)
            button.setIcon(preset_icon(preset["colors"]))
            button.setIconSize(QSize(68, 30))
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip("应用" + preset["name"] + "配色")
            button.clicked.connect(
                lambda _checked=False, key=preset["id"]: self.selectPreset(key))
            self._preset_group.addButton(button)
            self._preset_buttons[preset["id"]] = button
            preset_grid.addWidget(button, index // 2, index % 2)
        ll.addLayout(preset_grid)
        ll.addSpacing(4)
        preview_title = QLabel("实时预览")
        preview_title.setObjectName("CardTitle")
        ll.addWidget(preview_title)
        self.preview = ThemePreview(self._colors)
        ll.addWidget(self.preview, 1)
        body.addWidget(left)

        right = QFrame()
        right.setObjectName("ThemePickerPanel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 14, 16, 16)
        rl.setSpacing(10)
        custom_title = QLabel("自定义调色")
        custom_title.setObjectName("CardTitle")
        rl.addWidget(custom_title)
        editor = QHBoxLayout()
        editor.setSpacing(16)
        fields = QVBoxLayout()
        fields.setSpacing(6)
        self._field_group = QButtonGroup(self)
        self._field_group.setExclusive(True)
        for key, label in THEME_FIELDS:
            button = QPushButton()
            button.setObjectName("ThemeColorRow")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, name=key: self.selectField(name))
            self._field_group.addButton(button)
            self._field_buttons[key] = button
            fields.addWidget(button)
        fields.addStretch(1)
        editor.addLayout(fields, 1)

        picker = QVBoxLayout()
        picker.setSpacing(7)
        self.wheel = ColorWheel()
        self.wheel.colorChanged.connect(self._wheel_changed)
        picker.addWidget(self.wheel, 0, Qt.AlignHCenter)
        brightness_row = QHBoxLayout()
        brightness_row.addWidget(QLabel("亮度"))
        self.brightness = QSlider(Qt.Horizontal)
        self.brightness.setRange(0, 100)
        self.brightness.valueChanged.connect(self._brightness_changed)
        brightness_row.addWidget(self.brightness, 1)
        picker.addLayout(brightness_row)
        hex_row = QHBoxLayout()
        hex_row.addWidget(QLabel("颜色值"))
        self.hex_edit = QLineEdit()
        self.hex_edit.setObjectName("ThemeHex")
        self.hex_edit.setMaxLength(7)
        self.hex_edit.editingFinished.connect(self._hex_changed)
        hex_row.addWidget(self.hex_edit, 1)
        picker.addLayout(hex_row)
        picker.addWidget(QLabel("推荐配色"))
        recommendations = QGridLayout()
        recommendations.setSpacing(7)
        for index in range(12):
            button = QPushButton("")
            button.setFixedSize(27, 27)
            button.setCursor(Qt.PointingHandCursor)
            button.setAccessibleName("推荐颜色")
            button.clicked.connect(
                lambda _checked=False, item=button: self._recommend(
                    item.property("themeColor")))
            self._recommend_buttons.append(button)
            recommendations.addWidget(button, index // 6, index % 6)
        picker.addLayout(recommendations)
        picker.addStretch(1)
        editor.addLayout(picker)
        rl.addLayout(editor, 1)
        body.addWidget(right, 1)

        actions = QHBoxLayout()
        restore = QPushButton("恢复经典黑")
        restore.clicked.connect(lambda: self.selectPreset(DEFAULT_THEME_ID))
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.btn_apply = QPushButton("应用配色")
        self.btn_apply.setObjectName("Primary")
        self.btn_apply.clicked.connect(self.accept)
        actions.addWidget(restore)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(self.btn_apply)
        root.addLayout(actions)

        self._refresh()
        self.selectField("accent")

    def _set_preset_checks(self):
        self._preset_group.setExclusive(False)
        for key, button in self._preset_buttons.items():
            button.setChecked(key == self._preset_id)
        self._preset_group.setExclusive(True)

    def _mark_custom(self):
        self._preset_id = "custom"
        self._set_preset_checks()
        self.badge.setText("自定义")

    def selectPreset(self, preset_id):
        if preset_id not in PRESET_BY_ID:
            return
        self._preset_id = preset_id
        self._colors = preset_colors(preset_id)
        self._refresh()

    def selectField(self, key):
        if key not in EDITABLE_COLOR_KEYS:
            return
        self._field = key
        for name, button in self._field_buttons.items():
            button.setChecked(name == key)
        self._sync_picker()
        self._refresh_recommendations()

    def _recommendation_values(self):
        if self._field == "accent":
            return ACCENT_RECOMMENDATIONS
        if self._field in ("text", "text_dim"):
            return TEXT_RECOMMENDATIONS
        return BACKGROUND_RECOMMENDATIONS

    def _refresh_recommendations(self):
        for button, color in zip(self._recommend_buttons,
                                 self._recommendation_values()):
            text = best_text_color(color)
            button.setProperty("themeColor", color)
            button.setToolTip(color)
            button.setStyleSheet(
                f"QPushButton{{background:{color}; border:2px solid {C['border']};"
                f"border-radius:13px; padding:0; color:{text};}}"
                f"QPushButton:hover{{border-color:{C['accent']};}}")

    def _sync_picker(self):
        color = self._colors[self._field]
        self._syncing = True
        self.wheel.setColor(color)
        self.brightness.setValue(round(self.wheel.value() * 100))
        self.hex_edit.setText(color)
        self._syncing = False

    def _set_current_color(self, color):
        color = normalize_hex_color(color, self._colors[self._field])
        if color == self._colors[self._field]:
            self._sync_picker()
            return
        self._colors[self._field] = color
        self._mark_custom()
        self._refresh_color_rows()
        self.preview.setColors(self._colors)
        self._sync_picker()

    def _wheel_changed(self, color):
        if not self._syncing:
            self._set_current_color(color)

    def _brightness_changed(self, value):
        if not self._syncing:
            self.wheel.setValue(value / 100.0, emit=True)

    def _hex_changed(self):
        raw = self.hex_edit.text().strip()
        if len(raw) == 6 and not raw.startswith("#"):
            raw = "#" + raw
        if normalize_hex_color(raw, "") == raw.upper() and len(raw) == 7:
            self._set_current_color(raw)
        else:
            self._sync_picker()

    def _recommend(self, color):
        if color:
            self._set_current_color(color)

    def _refresh_color_rows(self):
        labels = dict(THEME_FIELDS)
        for key, button in self._field_buttons.items():
            color = self._colors[key]
            button.setText(f"{labels[key]}    {color}")
            button.setIcon(color_swatch_icon(color))
            button.setIconSize(QSize(20, 20))

    def _refresh(self):
        self._set_preset_checks()
        self.badge.setText(
            PRESET_BY_ID[self._preset_id]["name"]
            if self._preset_id in PRESET_BY_ID else "自定义")
        self._refresh_color_rows()
        self.preview.setColors(self._colors)
        self._sync_picker()
        self._refresh_recommendations()

    def selectedTheme(self):
        return self._preset_id, dict(self._colors)
