import sys
import json
import os
import requests
import ipaddress
from functools import partial

from PySide6.QtCore import Qt, Slot, Signal, QObject, QThread, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTextEdit,
    QMessageBox, QStatusBar, QScrollArea,
    QSizePolicy, QFrame, QSplitter
)

BOOKMARKS_FILE = "ip_bookmarks.json"

LIGHT_STYLE = """
    QWidget {
        background-color: #f0f0f0; color: #333333; font-size: 10pt;
    }
    QMainWindow, QStatusBar { background-color: #e0e0e0; }
    QLineEdit, QTextEdit, QScrollArea, QWebEngineView {
        background-color: #ffffff; color: #333333; border: 1px solid #c0c0c0;
        border-radius: 4px; padding: 4px;
    }
    QWebEngineView { padding: 0px; }
    QTextEdit#ResultsDisplay { font-size: 10pt; }
    QPushButton {
        background-color: #e0e0e0; border: 1px solid #b0b0b0;
        padding: 6px 10px; border-radius: 4px; min-height: 20px;
    }
    QPushButton:hover { background-color: #d0d0d0; }
    QPushButton:pressed { background-color: #c0c0c0; }
    QWidget#BookmarkEntry {
        border: 1px solid #cccccc; border-radius: 4px;
        margin-bottom: 4px; background-color: #f9f9f9;
    }
    QWidget#BookmarkEntry QLabel { background-color: transparent; border: none; }
    QWidget#BookmarkEntry QPushButton { padding: 4px 8px; font-size: 9pt; }
"""
DARK_STYLE = """
    QWidget {
        background-color: #2e2e2e; color: #e0e0e0; font-size: 10pt;
    }
    QMainWindow, QStatusBar { background-color: #252525; }
    QLineEdit, QTextEdit, QScrollArea, QWebEngineView {
        background-color: #3c3c3c; color: #e0e0e0; border: 1px solid #505050;
        border-radius: 4px; padding: 4px;
    }
    QWebEngineView { padding: 0px; }
    QTextEdit#ResultsDisplay { font-size: 10pt; }
    QPushButton {
        background-color: #505050; color: #e0e0e0; border: 1px solid #606060;
        padding: 6px 10px; border-radius: 4px; min-height: 20px;
    }
    QPushButton:hover { background-color: #606060; }
    QPushButton:pressed { background-color: #707070; }
    QWidget#BookmarkEntry {
        border: 1px solid #444444; border-radius: 4px;
        margin-bottom: 4px; background-color: #353535;
    }
    QWidget#BookmarkEntry QLabel { background-color: transparent; border: none; }
    QWidget#BookmarkEntry QPushButton { padding: 4px 8px; font-size: 9pt; }
"""

class IpInfoWorker(QObject):
    finished = Signal(object, object)
    progress = Signal(str)
    def __init__(self, ip_address, context=None):
        super().__init__()
        self.ip_address = ip_address
        self.context = context if context is not None else {}
        self._is_running = True
    @Slot()
    def run(self):
        if not self._is_running:
            self.finished.emit(RuntimeError("Operation cancelled by user"), self.context)
            return
        self.progress.emit(f"Fetching information for {self.ip_address}...")
        api_url = f"https://ipinfo.io/{self.ip_address}/json"
        try:
            response = requests.get(api_url, timeout=10)
            response.raise_for_status()
            data = response.json()
            if self._is_running: self.finished.emit(data, self.context)
        except Exception as e:
            if self._is_running: self.finished.emit(e, self.context)
    def stop(self): self._is_running = False


class IPLookupWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IP Address Lookup with Live Map")
        self.setGeometry(100, 100, 950, 800)
        self.setWindowIcon(QIcon("icon.png"))

        self.current_worker = None
        self.current_thread = None
        self.current_ip_data = None
        self.bookmarks = []
        self.editing_bookmark_index = -1
        self.is_dark_mode = False

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        input_area_widget = QWidget()
        input_layout = QHBoxLayout(input_area_widget)
        self.ip_label = QLabel("Enter IP Address:")
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("e.g., 8.8.8.8 or 2001:4860:4860::8888")
        self.lookup_button = QPushButton("Lookup IP")
        self.bookmark_ip_button = QPushButton("Bookmark IP")
        self.bookmark_ip_button.setEnabled(False)
        self.theme_toggle_button = QPushButton("Toggle Theme")
        input_layout.addWidget(self.ip_label)
        input_layout.addWidget(self.ip_input)
        input_layout.addWidget(self.lookup_button)
        input_layout.addWidget(self.bookmark_ip_button)
        input_layout.addStretch(1)
        input_layout.addWidget(self.theme_toggle_button)
        main_layout.addWidget(input_area_widget)

        self.info_and_map_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.results_display = QTextEdit()
        self.results_display.setObjectName("ResultsDisplay")
        self.results_display.setReadOnly(True)
        self.results_display.setPlaceholderText("IP information will be displayed here.")
        self.info_and_map_splitter.addWidget(self.results_display)

        self.map_view = QWebEngineView()
        self.info_and_map_splitter.addWidget(self.map_view)

        self.info_and_map_splitter.setSizes([self.width() // 2, self.width() // 2])
        main_layout.addWidget(self.info_and_map_splitter, 1)

        separator = QFrame(); separator.setFrameShape(QFrame.Shape.HLine); separator.setFrameShadow(QFrame.Shadow.Sunken)
        main_layout.addWidget(separator)
        bookmarks_title_label = QLabel("Bookmarked IPs")
        bookmarks_title_label.setStyleSheet("font-weight: bold; font-size: 12pt; margin-top: 5px;")
        main_layout.addWidget(bookmarks_title_label)
        self.bookmarks_scroll_area = QScrollArea(); self.bookmarks_scroll_area.setWidgetResizable(True)
        self.bookmarks_widget_container = QWidget()
        self.bookmarks_layout = QVBoxLayout(self.bookmarks_widget_container)
        self.bookmarks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.bookmarks_scroll_area.setWidget(self.bookmarks_widget_container)
        main_layout.addWidget(self.bookmarks_scroll_area, 1)

        self.status_bar = QStatusBar(); self.setStatusBar(self.status_bar); self.status_bar.showMessage("Ready")

        self.lookup_button.clicked.connect(self.on_lookup_clicked)
        self.ip_input.returnPressed.connect(self.on_lookup_clicked)
        self.bookmark_ip_button.clicked.connect(self.on_bookmark_current_ip_clicked)
        self.theme_toggle_button.clicked.connect(self.toggle_theme)

        self.load_bookmarks()
        self.render_bookmarks_list()
        self.apply_theme()
        self._update_map_display(None)

    def apply_theme(self):
        style = DARK_STYLE if self.is_dark_mode else LIGHT_STYLE
        QApplication.instance().setStyleSheet(style)
        self.theme_toggle_button.setText("Light Mode" if self.is_dark_mode else "Dark Mode")
        self._update_map_display(self.current_ip_data.get('loc') if self.current_ip_data else None)

    @Slot()
    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.apply_theme()
    
    @Slot()
    def on_lookup_clicked(self):
        ip_text = self.ip_input.text().strip()
        if not self._validate_ip_format(ip_text): return
        self.results_display.clear()
        self._update_map_display(None)
        self.current_ip_data = None
        self.bookmark_ip_button.setEnabled(False)
        self._start_worker(ip_text, context={'type': 'lookup'})

    @Slot(object, object)
    def handle_api_result(self, result, context):
        self.lookup_button.setEnabled(True)
        context_type = context.get('type', 'unknown')
        original_ip_for_update = context.get('original_ip_for_update')
        
        if isinstance(result, Exception):
            self._update_map_display(None)
            return
            
        if isinstance(result, dict):
            if context_type == 'lookup':
                self.current_ip_data = result
                self._display_ip_info(result)
                self._update_map_display(result.get('loc'))
                self.status_bar.showMessage(f"Fetched info for {result.get('ip', 'N/A')}.")
                self.bookmark_ip_button.setEnabled(not any(b['ip'] == result.get('ip') for b in self.bookmarks))

            elif context_type == 'bookmark_update':
                new_ip_data = result
                target_index = -1
                for idx, bm in enumerate(self.bookmarks):
                    if bm['ip'] == original_ip_for_update:
                        target_index = idx
                        break
                if target_index != -1:
                    self.bookmarks[target_index] = new_ip_data.copy()
                    self.save_bookmarks()
                    self.editing_bookmark_index = -1
                    self._display_ip_info(new_ip_data)
                    self._update_map_display(new_ip_data.get('loc'))
                self.render_bookmarks_list()

    def _display_ip_info(self, data_dict):
        if not data_dict or not isinstance(data_dict, dict):
            self.results_display.setHtml("<font color='orange'>No data to display.</font>")
            return
        ip = data_dict.get('ip', 'N/A')
        city = data_dict.get('city', 'N/A')
        region = data_dict.get('region', 'N/A')
        country = data_dict.get('country', 'N/A')
        org = data_dict.get('org', 'N/A')
        hostname = data_dict.get('hostname', 'N/A')

        output_html = f"""
        <b>IP Address:</b> {ip}<br>
        <b>Hostname:</b> {hostname if hostname else 'N/A'}<br>
        <b>City:</b> {city if city else 'N/A'}<br>
        <b>Region:</b> {region if region else 'N/A'}<br>
        <b>Country:</b> {country if country else 'N/A'}<br>
        <b>Organization:</b> {org if org else 'N/A'}<br>
        """
        self.results_display.setHtml(output_html)
        self.ip_input.setText(ip)

    def _update_map_display(self, location_coordinates_str):
        if location_coordinates_str and location_coordinates_str != 'N/A':
            try:
                lat, lon = [float(c.strip()) for c in location_coordinates_str.split(',')]
                html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                  <title>OpenLayers Map</title>
                  <meta charset="utf-8" />
                  <style>
                    html, body, #map {{
                      margin: 0;
                      padding: 0;
                      width: 100%;
                      height: 100%;
                    }}
                  </style>
                  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/ol@v7.4.0/ol.css">
                  <script src="https://cdn.jsdelivr.net/npm/ol@v7.4.0/dist/ol.js"></script>
                </head>
                <body>
                  <div id="map"></div>
                  <script>
                    var map = new ol.Map({{
                      target: 'map',
                      layers: [
                        new ol.layer.Tile({{
                          source: new ol.source.OSM()
                        }})
                      ],
                      view: new ol.View({{
                        center: ol.proj.fromLonLat([{lon}, {lat}]),
                        zoom: 11
                      }})
                    }});
                    var marker = new ol.Feature({{
                      geometry: new ol.geom.Point(ol.proj.fromLonLat([{lon}, {lat}]))
                    }});
                    var vectorSource = new ol.source.Vector({{
                      features: [marker]
                    }});
                    var markerVectorLayer = new ol.layer.Vector({{
                      source: vectorSource
                    }});
                    map.addLayer(markerVectorLayer);
                  </script>
                </body>
                </html>
                """
                self.map_view.setHtml(html)
            except (ValueError, IndexError):
                html_content = f"<body style='background-color:{'#2e2e2e' if self.is_dark_mode else '#f0f0f0'}; color:{'#e0e0e0' if self.is_dark_mode else '#333'}; text-align:center; padding-top: 20px;'>Invalid location data.</body>"
                self.map_view.setHtml(html_content)
        else:
            html_content = f"<body style='background-color:{'#2e2e2e' if self.is_dark_mode else '#f0f0f0'}; color:{'#e0e0e0' if self.is_dark_mode else '#333'}; text-align:center; padding-top: 20px;'>Map will be displayed here.</body>"
            self.map_view.setHtml(html_content)

    @Slot()
    def on_show_bookmark_details_clicked(self, index):
        if 0 <= index < len(self.bookmarks):
            bookmark_data = self.bookmarks[index]
            self.current_ip_data = bookmark_data
            self._display_ip_info(bookmark_data)
            self._update_map_display(bookmark_data.get('loc'))
            self.status_bar.showMessage(f"Displaying bookmarked IP: {bookmark_data.get('ip')}")
            self.bookmark_ip_button.setEnabled(False)
    
    def _start_worker(self, ip_address, context):
        self.lookup_button.setEnabled(False); self.bookmark_ip_button.setEnabled(False)
        self.status_bar.showMessage(f"Processing {ip_address}...")
        if self.current_thread and self.current_thread.isRunning():
            if self.current_worker: self.current_worker.stop()
            self.current_thread.quit(); self.current_thread.wait(1000)
        self.current_thread = QThread(self)
        self.current_worker = IpInfoWorker(ip_address, context)
        self.current_worker.moveToThread(self.current_thread)
        self.current_worker.finished.connect(self.handle_api_result)
        self.current_worker.progress.connect(self.status_bar.showMessage)
        self.current_thread.started.connect(self.current_worker.run)
        self.current_thread.finished.connect(self.current_thread.deleteLater)
        self.current_worker.finished.connect(self.current_worker.deleteLater)
        self.current_thread.start()

    def _validate_ip_format(self, ip_text, show_error_dialog=True):
        if not ip_text:
            if show_error_dialog: QMessageBox.warning(self, "Input Error", "Please enter an IP address.")
            return False
        try: ipaddress.ip_address(ip_text); return True
        except ValueError:
            if show_error_dialog: QMessageBox.warning(self, "Invalid IP", f"'{ip_text}' is not valid.")
            self.status_bar.showMessage("Invalid IP address format.")
            return False

    def _format_error_message(self, error_obj):
        error_message = f"Error: {str(error_obj)}"
        if isinstance(error_obj, requests.exceptions.HTTPError):
            error_message = f"API Error: {error_obj.response.status_code} - {error_obj.response.reason}"
        return error_message
    def load_bookmarks(self):
        if os.path.exists(BOOKMARKS_FILE):
            try:
                with open(BOOKMARKS_FILE, 'r', encoding='utf-8') as f: self.bookmarks = json.load(f)
            except (json.JSONDecodeError, Exception) as e: self.bookmarks = []; QMessageBox.warning(self, "Load Error", f"Could not load '{BOOKMARKS_FILE}': {e}")
        else: self.bookmarks = []
    def save_bookmarks(self):
        try:
            with open(BOOKMARKS_FILE, 'w', encoding='utf-8') as f: json.dump(self.bookmarks, f, indent=2)
        except Exception as e: QMessageBox.critical(self, "Save Error", f"Could not save: {e}")
    @Slot()
    def on_bookmark_current_ip_clicked(self):
        if not self.current_ip_data or 'ip' not in self.current_ip_data: return
        ip_to_bookmark = self.current_ip_data['ip']
        if any(b['ip'] == ip_to_bookmark for b in self.bookmarks): return
        self.bookmarks.append(self.current_ip_data.copy()); self.save_bookmarks()
        self.render_bookmarks_list(); self.status_bar.showMessage(f"IP {ip_to_bookmark} bookmarked.")
        self.bookmark_ip_button.setEnabled(False)
    def render_bookmarks_list(self):
        while self.bookmarks_layout.count():
            child = self.bookmarks_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
        if not self.bookmarks:
            no_bookmarks_label = QLabel("No bookmarks yet."); no_bookmarks_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bookmarks_layout.addWidget(no_bookmarks_label)
            return
        for index, bookmark_data in enumerate(self.bookmarks):
            entry_widget = self._create_bookmark_entry_widget(bookmark_data, index)
            self.bookmarks_layout.addWidget(entry_widget)
    def _create_bookmark_entry_widget(self, bookmark_data, index):
        entry_widget = QWidget(); entry_widget.setObjectName("BookmarkEntry")
        entry_layout = QHBoxLayout(entry_widget); entry_layout.setContentsMargins(5, 5, 5, 5)
        ip_addr, city = bookmark_data.get('ip', 'N/A'), bookmark_data.get('city', 'N/A')
        identifier_text = f"{ip_addr} ({city if city else 'Unknown'})"
        if self.editing_bookmark_index == index:
            ip_edit_input = QLineEdit(ip_addr); entry_layout.addWidget(ip_edit_input, 2)
            save_button = QPushButton("Save"); save_button.clicked.connect(partial(self.on_save_edited_bookmark_clicked, index, ip_edit_input)); entry_layout.addWidget(save_button)
            cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(partial(self.on_cancel_edit_bookmark_clicked, index)); entry_layout.addWidget(cancel_button)
        else:
            label = QLabel(identifier_text); label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred); entry_layout.addWidget(label, 2)
            show_details_button = QPushButton("Show Details"); show_details_button.clicked.connect(partial(self.on_show_bookmark_details_clicked, index)); entry_layout.addWidget(show_details_button)
            edit_button = QPushButton("Edit"); edit_button.clicked.connect(partial(self.on_edit_bookmark_clicked, index)); entry_layout.addWidget(edit_button)
            delete_button = QPushButton("Delete"); delete_button.clicked.connect(partial(self.on_delete_bookmark_clicked, index)); entry_layout.addWidget(delete_button)
        return entry_widget
    @Slot()
    def on_edit_bookmark_clicked(self, index):
        if self.editing_bookmark_index != -1 and self.editing_bookmark_index != index: return
        self.editing_bookmark_index = index; self.render_bookmarks_list()
    @Slot()
    def on_delete_bookmark_clicked(self, index):
        if 0 <= index < len(self.bookmarks):
            ip_to_delete = self.bookmarks[index]['ip']
            if QMessageBox.question(self, "Confirm Delete", f"Delete {ip_to_delete}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                del self.bookmarks[index]; self.save_bookmarks()
                if self.editing_bookmark_index == index: self.editing_bookmark_index = -1
                self.render_bookmarks_list()
                if self.current_ip_data and self.current_ip_data.get('ip') == ip_to_delete: self.bookmark_ip_button.setEnabled(True)
    @Slot()
    def on_save_edited_bookmark_clicked(self, index, ip_edit_input_widget):
        new_ip_text = ip_edit_input_widget.text().strip(); original_ip = self.bookmarks[index]['ip']
        if not self._validate_ip_format(new_ip_text): return
        if new_ip_text == original_ip: self.editing_bookmark_index = -1; self.render_bookmarks_list(); return
        if any(i != index and bm['ip'] == new_ip_text for i, bm in enumerate(self.bookmarks)): return
        self._start_worker(new_ip_text, context={'type': 'bookmark_update', 'original_ip_for_update': original_ip})
    @Slot()
    def on_cancel_edit_bookmark_clicked(self, index):
        self.editing_bookmark_index = -1; self.render_bookmarks_list()
    def closeEvent(self, event):
        if self.current_thread and self.current_thread.isRunning():
            if self.current_worker: self.current_worker.stop()
            self.current_thread.quit(); self.current_thread.wait(1500)
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = IPLookupWindow()
    window.show()
    sys.exit(app.exec())
