"""Profile manager and simple HTML info-dialog helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout, QWidget,
)


NO_PROFILE = "(no profile)"


def mirror_tooltips_to_accessibility(root: QWidget) -> None:
    """Tooltips only show on mouse hover, so screen readers never see
    them. Copy each widget's tooltip into its accessibleDescription,
    which assistive technology announces on keyboard focus. Call once
    at the end of a dialog's __init__ (main_window does the same for
    its own widget tree at startup)."""
    for w in root.findChildren(QWidget):
        if w.toolTip() and not w.accessibleDescription():
            w.setAccessibleDescription(w.toolTip())


# ============================================================== WatchFolderDialog

class WatchFolderDialog(QDialog):
    """Configure + start the folder-watching daemon.

    Opens modeless: the user picks a folder, a "done" subfolder name, and
    clicks Start. The watcher then runs in the background; this dialog
    can be closed and re-opened later to see the live counter or stop
    watching.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("Veloxa Video Editor — Watch Folder")
        self.setWindowIcon(parent.app_icon)
        self.resize(620, 320)

        v = QVBoxLayout(self)
        title = QLabel('<h2 style="color:#f58220; margin:0;">Watch Folder</h2>')
        v.addWidget(title)

        info = QLabel(
            "Watch a folder for new media files. Each file that lands "
            "in the folder is auto-added to the queue and encoded with "
            "the currently loaded profile. When the batch finishes, "
            "successfully-encoded sources move to the &quot;done&quot; "
            "subfolder so they don't get re-processed.")
        info.setProperty("role", "muted")
        info.setWordWrap(True)
        v.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Folder to watch:"))
        self.folder_path = QLineEdit()
        self.folder_path.setReadOnly(True)
        self.folder_path.setPlaceholderText("(no folder selected)")
        self.folder_path.setToolTip(
            "Folder monitored for new media files. Use Browse to "
            "change it.")
        existing = parent.settings.value("watch_folder", "")
        if existing:
            self.folder_path.setText(existing)
        row.addWidget(self.folder_path, 1)
        browse = QPushButton("📂 Browse...")
        browse.setToolTip("Choose the folder to watch.")
        browse.clicked.connect(self._pick_folder)
        row.addWidget(browse)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Move processed files to subfolder:"))
        self.done_subfolder = QLineEdit(
            parent.settings.value("watch_done_subfolder", "done"))
        self.done_subfolder.setMaxLength(64)
        self.done_subfolder.setToolTip(
            "Name of the subfolder (created inside the watched folder) "
            "where successfully-encoded source files are moved so they "
            "aren't processed twice.")
        row2.addWidget(self.done_subfolder, 1)
        v.addLayout(row2)

        self.status_lbl = QLabel("Not watching.")
        self.status_lbl.setStyleSheet(
            "background:#232529; padding:8px; border:1px solid #454952; "
            "border-radius:5px;")
        self.status_lbl.setWordWrap(True)
        v.addWidget(self.status_lbl)

        v.addStretch(1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.start_btn = QPushButton("▶ Start Watching")
        self.start_btn.setObjectName("primary")
        self.start_btn.setToolTip(
            "Begin monitoring the folder. New media files are added to "
            "the queue and encoded automatically.")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setToolTip(
            "Stop monitoring. Files already in the queue are not "
            "removed.")
        self.stop_btn.clicked.connect(self._on_stop)
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(self.start_btn)
        bottom.addWidget(self.stop_btn)
        bottom.addWidget(close_btn)
        v.addLayout(bottom)

        self._refresh_state()
        mirror_tooltips_to_accessibility(self)

    def _pick_folder(self):
        f = QFileDialog.getExistingDirectory(
            self, "Folder to Watch",
            self.folder_path.text() or self.main.settings.value("last_dir", ""))
        if f:
            self.folder_path.setText(f)

    def _refresh_state(self):
        watching = self.main._watcher is not None
        if watching:
            count = self.main._watch_processed
            self.status_lbl.setText(
                f"Watching <b>{self.main._watcher.folder}</b> &mdash; "
                f"{count} file(s) processed since this session started.")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
        else:
            self.status_lbl.setText("Not watching.")
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def _on_start(self):
        folder = self.folder_path.text().strip()
        if not folder:
            QMessageBox.information(self, "Folder Required",
                                    "Pick a folder to watch.")
            return
        if not Path(folder).is_dir():
            QMessageBox.critical(self, "Invalid Folder",
                                 f"Not a folder:\n{folder}")
            return
        sub = self.done_subfolder.text().strip() or "done"
        self.main._start_watch(folder, sub)
        self.main.settings.setValue("watch_folder", folder)
        self.main.settings.setValue("watch_done_subfolder", sub)
        self._refresh_state()

    def _on_stop(self):
        self.main._stop_watch()
        self._refresh_state()


# ============================================================== InfoDialog

def show_info_dialog(parent, title: str, html: str):
    """Modal HTML viewer used for README / Install / Help / License."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Veloxa Video Editor — {title}")
    if hasattr(parent, "app_icon"):
        dlg.setWindowIcon(parent.app_icon)
    dlg.resize(780, 640)
    v = QVBoxLayout(dlg)
    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setHtml(html)
    v.addWidget(browser, 1)

    row = QHBoxLayout()
    row.addStretch()
    close_btn = QPushButton("✕ Close")
    close_btn.setObjectName("primary")
    close_btn.clicked.connect(dlg.accept)
    close_btn.setDefault(True)
    row.addWidget(close_btn)
    v.addLayout(row)
    dlg.exec()


# ============================================================== ManageSavedDataDialog

class ManageSavedDataDialog(QDialog):
    """Browse + delete the per-profile asset bundles V11.1 saves under
    ``%APPDATA%\\Veloxa-VD\\profile_assets``.

    Each row shows a profile name, the number of asset files, and the
    on-disk size. Buttons: delete the highlighted row's bundle, delete
    everything, refresh, or open the asset root in Explorer.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("Veloxa Video Editor — Manage Saved Profile Data")
        if hasattr(parent, "app_icon"):
            self.setWindowIcon(parent.app_icon)
        self.resize(640, 420)

        v = QVBoxLayout(self)

        intro = QLabel(
            "Each profile keeps its referenced watermark image and "
            "watermark video inside the app so the profile keeps working "
            "even if you move or delete the originals. You can clear "
            "the saved data here to reclaim disk space."
        )
        intro.setWordWrap(True)
        v.addWidget(intro)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Profile", "Files", "Size"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        v.addWidget(self.table, 1)

        self.total_lbl = QLabel("")
        self.total_lbl.setProperty("role", "muted")
        v.addWidget(self.total_lbl)

        row = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setToolTip("Re-scan the saved data and update the table.")
        self.refresh_btn.clicked.connect(self._refresh)
        row.addWidget(self.refresh_btn)
        self.open_btn = QPushButton("📂 Open Folder")
        self.open_btn.setToolTip(
            "Open the folder where profile assets are stored, in your "
            "file manager.")
        self.open_btn.clicked.connect(self._open_folder)
        row.addWidget(self.open_btn)
        row.addStretch()
        self.del_one_btn = QPushButton("🗑 Delete Selected")
        self.del_one_btn.setToolTip(
            "Delete the selected profile's saved watermark files. The "
            "profile itself is kept, but it will need its watermark "
            "files re-picked to keep working.")
        self.del_one_btn.clicked.connect(self._delete_selected)
        row.addWidget(self.del_one_btn)
        self.del_all_btn = QPushButton("🗑 Delete ALL")
        self.del_all_btn.setObjectName("danger")
        self.del_all_btn.setToolTip(
            "Delete every profile's saved watermark files to reclaim "
            "disk space. Asks for confirmation first.")
        self.del_all_btn.clicked.connect(self._delete_all)
        row.addWidget(self.del_all_btn)
        close_btn = QPushButton("✕ Close")
        close_btn.setObjectName("primary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        v.addLayout(row)

        self._refresh()
        mirror_tooltips_to_accessibility(self)

    # ------------------------------------------------------ helpers

    @staticmethod
    def _fmt_size(n_bytes: int) -> str:
        if n_bytes < 1024:
            return f"{n_bytes} B"
        if n_bytes < 1024 ** 2:
            return f"{n_bytes / 1024:.1f} KB"
        if n_bytes < 1024 ** 3:
            return f"{n_bytes / (1024 ** 2):.1f} MB"
        return f"{n_bytes / (1024 ** 3):.2f} GB"

    def _refresh(self):
        # Imported here so a missing module never blocks the rest of the app.
        from .profile_assets import profile_asset_summary
        rows = profile_asset_summary()
        self.table.setRowCount(len(rows))
        total_bytes = 0
        for i, r in enumerate(rows):
            total_bytes += r["size_bytes"]
            self.table.setItem(i, 0, QTableWidgetItem(r["name"]))
            files_item = QTableWidgetItem(str(r["file_count"]))
            files_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 1, files_item)
            size_item = QTableWidgetItem(self._fmt_size(r["size_bytes"]))
            size_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 2, size_item)
            # Stash the absolute path on the row so delete-selected /
            # open-folder don't have to recompute it.
            self.table.item(i, 0).setData(Qt.ItemDataRole.UserRole, r["path"])
        if rows:
            self.total_lbl.setText(
                f"{len(rows)} profile bundle(s), "
                f"{self._fmt_size(total_bytes)} total")
        else:
            self.total_lbl.setText("No saved profile data.")
        self.del_one_btn.setEnabled(bool(rows))
        self.del_all_btn.setEnabled(bool(rows))

    def _selected_name(self):
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return None, None
        row = sel[0].row()
        item = self.table.item(row, 0)
        if item is None:
            return None, None
        return item.text(), item.data(Qt.ItemDataRole.UserRole)

    # ------------------------------------------------------ actions

    def _delete_selected(self):
        name, _path = self._selected_name()
        if not name:
            QMessageBox.information(self, "Delete",
                                    "Pick a profile to delete its data.")
            return
        r = QMessageBox.question(
            self, "Delete saved data",
            f"Delete the saved watermarks / assets for profile '{name}'?\n"
            f"\nThe profile itself will not be removed, but its watermarks "
            f"will be unset.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        from .profile_assets import (
            delete_profile_assets, ASSET_KEYS, PROFILE_VISUALS_KEY,
        )
        delete_profile_assets(name)
        # If the profile dict still references files inside the deleted
        # folder, blank those keys so loading the profile next time doesn't
        # try to read missing files.
        prof = (self.main.profiles or {}).get(name)
        if isinstance(prof, dict):
            for key, _stem in ASSET_KEYS:
                v = (prof.get(key) or "")
                if v and not os.path.exists(v):
                    prof[key] = ""
            # V11.3 fix (audit A4): also drop any orphaned audio-visual
            # entries so the profile_visuals list doesn't keep dead paths
            # forever after the user wipes the saved data.
            visuals = prof.get(PROFILE_VISUALS_KEY)
            if isinstance(visuals, list):
                prof[PROFILE_VISUALS_KEY] = [
                    e for e in visuals
                    if isinstance(e, dict) and e.get("path")
                    and os.path.exists(e["path"])
                ]
            self.main.profiles[name] = prof
            try:
                self.main._save_profiles()
            except Exception:
                pass
        self._refresh()

    def _delete_all(self):
        r = QMessageBox.question(
            self, "Delete all saved data",
            "Delete the saved watermarks / assets for ALL profiles?\n\n"
            "Profiles themselves will not be removed, but their watermarks "
            "will be unset.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        from .profile_assets import (
            delete_all_profile_assets, ASSET_KEYS, PROFILE_VISUALS_KEY,
        )
        delete_all_profile_assets()
        # Blank any now-orphaned asset paths in every profile.
        if isinstance(self.main.profiles, dict):
            for prof in self.main.profiles.values():
                if not isinstance(prof, dict):
                    continue
                for key, _stem in ASSET_KEYS:
                    v = (prof.get(key) or "")
                    if v and not os.path.exists(v):
                        prof[key] = ""
                # V11.3 fix (audit A4): drop dead profile_visuals entries.
                visuals = prof.get(PROFILE_VISUALS_KEY)
                if isinstance(visuals, list):
                    prof[PROFILE_VISUALS_KEY] = [
                        e for e in visuals
                        if isinstance(e, dict) and e.get("path")
                        and os.path.exists(e["path"])
                    ]
            try:
                self.main._save_profiles()
            except Exception:
                pass
        self._refresh()

    def _open_folder(self):
        from .profile_assets import assets_root
        from .platform_compat import open_in_file_manager
        root = str(assets_root())
        if not open_in_file_manager(root):
            QMessageBox.information(self, "Folder", root)


# ============================================================== ProfileManagerDialog

class ProfileManagerDialog(QDialog):
    """Full profile management: list, create, rename, duplicate, delete,
    edit, import / export, plus a quick "create from image" action.

    Acts directly on ``parent.profiles`` and persists after every action so
    closing the dialog (X / Esc / Close) can never lose work.
    """

    UNDO_DEPTH = 50

    def __init__(self, parent):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("Veloxa Video Editor — Profile Manager")
        self.setWindowIcon(parent.app_icon)
        self.resize(880, 640)

        # Undo / redo stacks store snapshots of `main.profiles` taken
        # _before_ each mutating action.
        self._undo_stack = []
        self._redo_stack = []

        # Search filter (case-insensitive substring against profile names).
        self._search_text = ""

        self._build_ui()
        self._refresh_list()
        self._install_shortcuts()
        self._update_undo_buttons()
        mirror_tooltips_to_accessibility(self)

    # Convenience: read/write straight against the main window's profiles.
    @property
    def profiles(self):
        return self.main.profiles

    def _persist(self, status_msg: str = ""):
        self.main._save_profiles()
        self.main._refresh_profile_combo()
        # V11.5 fix (audit B4): every persist must also re-populate the
        # per-row profile combos in the queue so newly added / renamed
        # profiles are immediately pickable, and removed profiles stop
        # appearing as live options.
        try:
            self.main._refresh_per_row_combos_only()
        except Exception:
            pass
        # V12.1 audit fix (E4): any Profile Manager persist could have
        # mutated profile dicts that the per-batch row-opts cache is
        # holding (rename, delete, edit, import all go through here).
        # Wipe the cache so the next preview / info-bar / batch
        # re-resolves opts from the freshly-saved profiles.
        try:
            self.main._row_opts_cache = {}
        except Exception:
            pass
        if status_msg:
            self.main.status_lbl.setText(status_msg)

    # ---- UI -----------------------------------------------------

    def _build_ui(self):
        v = QVBoxLayout(self)
        v.setSpacing(10)

        title = QLabel('<h2 style="color:#f58220; margin:0;">Profile Manager</h2>')
        v.addWidget(title)

        info = QLabel(
            "Manage saved presets. Create from current settings, rename, "
            "duplicate, delete, import / export to share, or quickly bake a "
            "watermark image into a new profile."
        )
        info.setProperty("role", "muted")
        info.setWordWrap(True)
        v.addWidget(info)

        # Search bar above the list.
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter profiles by name (Ctrl+F)")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_box, 1)
        v.addLayout(search_row)

        h = QHBoxLayout()
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        h.addWidget(self.list, 2)

        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(False)
        self.details.setHtml(
            "<p style='color:#888'>Select a profile to view details.</p>")
        h.addWidget(self.details, 3)
        v.addLayout(h, 1)

        row1 = QHBoxLayout()
        new_btn = QPushButton("＋ New from Current")
        new_btn.setToolTip("Capture current main-window settings as a new profile (Ctrl+N)")
        new_btn.clicked.connect(self._new_from_current)
        edit_btn = QPushButton("✎ Edit Selected...")
        edit_btn.setToolTip(
            "Load the selected profile into the main window for editing. "
            "After tweaking settings, click 'Update Profile' in the header "
            "(or press Ctrl+S) to save changes back to this profile.")
        edit_btn.clicked.connect(self._edit_selected)
        rename_btn = QPushButton("✎ Rename...")
        rename_btn.setToolTip("Rename the selected profile (F2)")
        rename_btn.clicked.connect(self._rename_selected)
        number_btn = QPushButton("＃ Set Number...")
        number_btn.setToolTip(
            "Change the selected profile's sticky shortcut number -- "
            "the number you type on selected queue rows to assign this "
            "profile. If another profile already uses the number, the "
            "two profiles swap numbers.")
        number_btn.clicked.connect(self._set_number_selected)
        dup_btn = QPushButton("⎘ Duplicate")
        dup_btn.setToolTip("Duplicate the selected profile (Ctrl+D)")
        dup_btn.clicked.connect(self._duplicate_selected)
        del_btn = QPushButton("🗑 Delete")
        del_btn.setObjectName("danger")
        del_btn.setToolTip("Delete the selected profile (Delete)")
        del_btn.clicked.connect(self._delete_selected)
        row1.addWidget(new_btn); row1.addWidget(edit_btn)
        row1.addWidget(rename_btn); row1.addWidget(number_btn)
        row1.addWidget(dup_btn)
        row1.addWidget(del_btn)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        import_btn = QPushButton("⬇ Import...")
        import_btn.setToolTip("Import profile(s) from a .vvprof or .json file (Ctrl+I)")
        import_btn.clicked.connect(self._import)
        export_btn = QPushButton("⬆ Export Selected...")
        export_btn.setToolTip("Export the selected profile to a .vvprof file (Ctrl+E)")
        export_btn.clicked.connect(self._export_selected)
        export_all_btn = QPushButton("⬆ Export All...")
        export_all_btn.setToolTip("Export all profiles to a single .vvprof bundle")
        export_all_btn.clicked.connect(self._export_all)
        row2.addWidget(import_btn)
        row2.addWidget(export_btn)
        row2.addWidget(export_all_btn)
        row2.addStretch()
        self.undo_btn = QPushButton("↶ Undo")
        self.undo_btn.setToolTip("Undo last profile change (Ctrl+Z)")
        self.undo_btn.clicked.connect(self._undo)
        self.redo_btn = QPushButton("↷ Redo")
        self.redo_btn.setToolTip("Redo (Ctrl+Y)")
        self.redo_btn.clicked.connect(self._redo)
        row2.addWidget(self.undo_btn)
        row2.addWidget(self.redo_btn)
        v.addLayout(row2)

        quick = QGroupBox("Quick: create profile from a watermark image")
        qh = QHBoxLayout(quick)
        self.quick_img_path = QLineEdit()
        self.quick_img_path.setPlaceholderText("(no image selected)")
        self.quick_img_path.setReadOnly(True)
        self.quick_img_path.setToolTip(
            "Watermark image for the quick-created profile.")
        pick_btn = QPushButton("📂 Pick Image...")
        pick_btn.setToolTip("Choose the watermark image.")
        pick_btn.clicked.connect(self._pick_quick_image)
        create_btn = QPushButton("＋ Create Profile")
        create_btn.setObjectName("primary")
        create_btn.setToolTip(
            "Create a new profile named after the image, using current "
            "main-window settings plus this image as the watermark.")
        create_btn.clicked.connect(self._create_from_image)
        qh.addWidget(QLabel("Image:"))
        qh.addWidget(self.quick_img_path, 1)
        qh.addWidget(pick_btn)
        qh.addWidget(create_btn)
        v.addWidget(quick)

        bottom = QHBoxLayout()
        bottom.addStretch()
        load_btn = QPushButton("▶ Load Selected")
        load_btn.setObjectName("primary")
        load_btn.setToolTip(
            "Apply the selected profile to the main window and close "
            "this dialog.")
        load_btn.clicked.connect(self._load_and_close)
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(load_btn); bottom.addWidget(close_btn)
        v.addLayout(bottom)

    # ---- undo / redo --------------------------------------------

    def _take_snapshot(self) -> dict:
        return {k: dict(v) for k, v in self.main.profiles.items()}

    def _push_undo(self):
        """Capture current state BEFORE a mutation; clear the redo stack."""
        self._undo_stack.append(self._take_snapshot())
        # Cap to keep memory + visual list manageable.
        if len(self._undo_stack) > self.UNDO_DEPTH:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_buttons()

    def _undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._take_snapshot())
        self.main.profiles = self._undo_stack.pop()
        self._persist("Undid profile change")
        self._refresh_list()
        self._update_undo_buttons()

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._take_snapshot())
        self.main.profiles = self._redo_stack.pop()
        self._persist("Redid profile change")
        self._refresh_list()
        self._update_undo_buttons()

    def _update_undo_buttons(self):
        self.undo_btn.setEnabled(bool(self._undo_stack))
        self.redo_btn.setEnabled(bool(self._redo_stack))

    # ---- search -------------------------------------------------

    def _on_search_changed(self, text: str):
        self._search_text = text.strip().lower()
        self._refresh_list()

    # ---- shortcuts ----------------------------------------------

    def _install_shortcuts(self):
        def sc(seq, slot):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.ShortcutContext.WindowShortcut)
            s.activated.connect(slot)
            return s
        sc(QKeySequence.StandardKey.Undo, self._undo)
        sc(QKeySequence.StandardKey.Redo, self._redo)
        sc("Ctrl+Y", self._redo)
        sc(QKeySequence.StandardKey.Find, self.search_box.setFocus)
        sc("Ctrl+N", self._new_from_current)
        sc("F2", self._rename_selected)
        sc("Ctrl+D", self._duplicate_selected)
        sc("Ctrl+I", self._import)
        sc("Ctrl+E", self._export_selected)
        del_sc = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.list)
        del_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        del_sc.activated.connect(self._delete_selected)

    # ---- list helpers -------------------------------------------

    def _refresh_list(self):
        self.list.blockSignals(True)
        prev = self._selected_name()
        self.list.clear()
        needle = self._search_text
        for name in sorted(self.profiles.keys(), key=str.lower):
            if needle and needle not in name.lower():
                continue
            # V14.10.0: display the sticky shortcut number; the raw
            # name travels in UserRole so selection logic stays exact.
            it = QListWidgetItem(self.main._profile_label(name))
            it.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(it)
        self.list.blockSignals(False)
        if prev and prev in self.profiles and self._is_in_list(prev):
            self._select_by_name(prev)
        elif self.list.count() > 0:
            self.list.setCurrentRow(0)
        self._on_selection_changed()

    def _is_in_list(self, name: str) -> bool:
        for i in range(self.list.count()):
            it = self.list.item(i)
            raw = it.data(Qt.ItemDataRole.UserRole)
            if (raw if isinstance(raw, str) else it.text()) == name:
                return True
        return False

    def _ensure_visible(self, name: str):
        """Clear the search filter if it would hide ``name``, so a freshly
        created / renamed profile doesn't appear to vanish."""
        if not self._search_text:
            return
        if self._search_text in name.lower():
            return
        self.search_box.blockSignals(True)
        self.search_box.setText("")
        self.search_box.blockSignals(False)
        self._search_text = ""

    def _selected_name(self):
        item = self.list.currentItem()
        if item is None:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        return raw if isinstance(raw, str) else item.text()

    def _select_by_name(self, name: str):
        for i in range(self.list.count()):
            it = self.list.item(i)
            raw = it.data(Qt.ItemDataRole.UserRole)
            if (raw if isinstance(raw, str) else it.text()) == name:
                self.list.setCurrentRow(i)
                break

    def _on_selection_changed(self):
        name = self._selected_name()
        if not name or name not in self.profiles:
            self.details.setHtml(
                "<p style='color:#888'>Select a profile to view details.</p>")
            return
        d = self.profiles[name]
        rows = []

        def row(label, val):
            rows.append(
                f"<tr><td style='color:#888;padding-right:14px'>{label}</td>"
                f"<td>{val}</td></tr>")

        row("Shortcut number",
            d.get("shortcut_number", "—"))
        row("Codec", str(d.get("out_codec", "h264")).upper())
        row("Encoder", d.get("out_encoder", "(auto)"))
        row("Quality", d.get("out_quality", "Balanced"))
        row("Resolution", d.get("out_res", "4K (3840x2160)"))
        row("Parallel jobs", d.get("parallel_jobs", 1))
        row("Force stereo", "Yes" if d.get("force_stereo", True) else "No")
        row("Trim from start", f"{d.get('trim_start', 0)} s")
        row("Trim from end", f"{d.get('trim_end', 0)} s")
        wm = d.get("wm_path") or ""
        if wm:
            row("Image watermark", wm)
            row("WM position",
                f"{d.get('wm_preset', 'Bottom-Right')} "
                f"({d.get('wm_scale', 15)}% size, "
                f"{d.get('wm_opacity', 100)}% opacity)")
        else:
            row("Image watermark", "(none)")
        twm = (d.get("text_wm_text") or "").strip()
        if twm:
            row("Text watermark", twm)
            row("Text size / color",
                f"{d.get('text_wm_size', 36)} px, "
                f"{d.get('text_wm_color', '#ffffff')}")
        else:
            row("Text watermark", "(none)")
        row("Output suffix", d.get("out_suffix", "_edited"))

        html = (f"<h3 style='color:#f58220;margin-top:0'>{name}</h3>"
                f"<table cellspacing='4'>{''.join(rows)}</table>")
        self.details.setHtml(html)

    # ---- actions ------------------------------------------------

    def _new_from_current(self):
        suggest = ""
        if self.main.profile_combo.currentText() != NO_PROFILE:
            suggest = self.main.profile_combo.currentText()
        name, ok = QInputDialog.getText(
            self, "New Profile",
            "Name for new profile (captures current settings):", text=suggest)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name == NO_PROFILE:
            QMessageBox.information(self, "Reserved Name",
                                    "That name is reserved.")
            return
        if name in self.profiles:
            r = QMessageBox.question(self, "Overwrite?",
                                     f"Profile '{name}' exists. Overwrite?")
            if r != QMessageBox.StandardButton.Yes:
                return
        self._push_undo()
        self.main._store_profile(name, self.main._collect_settings_dict())
        self._ensure_visible(name)
        self._persist(f"Created profile: {name}")
        self._refresh_list()
        self._select_by_name(name)

    def _edit_selected(self):
        """Load the selected profile into the main window for editing,
        then close. The user tweaks settings in the main window and clicks
        the header's "Update Profile" button to save changes back."""
        name = self._selected_name()
        if not name or name not in self.profiles:
            QMessageBox.information(self, "Edit",
                                    "Select a profile to edit.")
            return
        self.main._apply_settings_dict(self.profiles[name])
        idx = self.main.profile_combo.findText(name)
        if idx >= 0:
            self.main.profile_combo.blockSignals(True)
            self.main.profile_combo.setCurrentIndex(idx)
            self.main.profile_combo.blockSignals(False)
        self.main.settings.setValue("last_profile", name)
        self.main._sync_seek_bar_trim()
        self.main._refresh_encoder_combo()
        self.main._schedule_preview()
        self.main._update_profile_button_state()
        self.main.status_lbl.setText(
            f"Editing profile '{name}' - tweak settings, then click "
            "'Update Profile' in the header to save changes")
        self.accept()

    def _set_number_selected(self):
        """V14.10.0: reassign the selected profile's sticky shortcut
        number. Swaps with the current holder on conflict."""
        name = self._selected_name()
        if not name or name not in self.profiles:
            return
        cur = self.main._profile_number(name) or 1
        n, ok = QInputDialog.getInt(
            self, "Set Shortcut Number",
            f"Shortcut number for '{name}'\n(typing this number on "
            "selected queue rows assigns this profile):",
            value=cur, min=1, max=999)
        if not ok or n == cur:
            return
        self._push_undo()
        self.main._set_profile_number(name, n)
        self._persist(f"Profile '{name}' is now #{n}.")
        self._refresh_list()
        self._select_by_name(name)

    def _rename_selected(self):
        old = self._selected_name()
        if not old or old not in self.profiles:
            return
        new, ok = QInputDialog.getText(self, "Rename Profile",
                                       "New name:", text=old)
        if not ok or not new.strip() or new == old:
            return
        new = new.strip()
        if new == NO_PROFILE:
            QMessageBox.information(self, "Reserved Name",
                                    "That name is reserved.")
            return
        if new in self.profiles:
            r = QMessageBox.question(self, "Overwrite?",
                                     f"Profile '{new}' exists. Overwrite?")
            if r != QMessageBox.StandardButton.Yes:
                return
        self._push_undo()
        # V11.3 fix (audit A2): a profile rename must also relocate the
        # on-disk asset folder, rewrite asset paths in the dict (so the
        # in-app copies still resolve), and migrate the rotation counter
        # to the new key. Otherwise the renamed profile loses its
        # watermarks/visuals and starts the rotation over from 0.
        import shutil as _shutil
        from .profile_assets import (
            assets_dir_for, ASSET_KEYS, PROFILE_VISUALS_KEY,
            rotation_key_for,
        )
        prof = self.profiles.pop(old)
        old_dir = assets_dir_for(old)
        new_dir = assets_dir_for(new)
        if old_dir.exists() and old_dir != new_dir:
            try:
                if new_dir.exists():
                    _shutil.rmtree(new_dir)
                old_dir.rename(new_dir)
            except OSError:
                # Fall back to copy-then-delete if rename across filesystems
                try:
                    _shutil.copytree(old_dir, new_dir)
                    _shutil.rmtree(old_dir, ignore_errors=True)
                except OSError:
                    pass
            # Rewrite watermark paths inside the dict so they point at
            # the new folder (only when they currently point at the old
            # one — leave external paths alone).
            old_str = str(old_dir)
            new_str = str(new_dir)
            for key, _stem in ASSET_KEYS:
                v = (prof.get(key) or "")
                if v.startswith(old_str):
                    prof[key] = new_str + v[len(old_str):]
            # Rewrite each profile_visuals path the same way.
            visuals = prof.get(PROFILE_VISUALS_KEY)
            if isinstance(visuals, list):
                for entry in visuals:
                    if not isinstance(entry, dict):
                        continue
                    p = entry.get("path") or ""
                    if p.startswith(old_str):
                        entry["path"] = new_str + p[len(old_str):]
        # Migrate the rotation counter under the new safe-name key.
        old_key = rotation_key_for(old)
        new_key = rotation_key_for(new)
        try:
            old_val = self.main.settings.value(old_key)
            if old_val is not None:
                self.main.settings.setValue(new_key, old_val)
            self.main.settings.remove(old_key)
            self.main.settings.sync()
        except Exception:
            pass
        self.profiles[new] = prof
        # If the renamed profile was the active one in the header combo,
        # update the "last loaded profile" pointer too.
        if self.main.settings.value("last_profile", "") == old:
            self.main.settings.setValue("last_profile", new)
        # V11.5 fix (audit B1): every queue row pinned to the OLD name
        # must follow the rename; otherwise _opts_for_row falls back to
        # the live form silently and the user encodes with the wrong
        # settings.
        try:
            self.main._rebase_queue_rows(renames={old: new})
        except Exception:
            pass
        self._ensure_visible(new)
        self._persist(f"Renamed: {old} -> {new}")
        self._refresh_list()
        self._select_by_name(new)

    def _duplicate_selected(self):
        old = self._selected_name()
        if not old or old not in self.profiles:
            return
        candidate = f"{old} copy"
        i = 2
        while candidate in self.profiles:
            candidate = f"{old} copy {i}"
            i += 1
        self._push_undo()
        # V11.3 fix (audit C2): use a deep copy so subsequent mutations
        # of profile_visuals (or any other nested list/dict) on either
        # the source or the duplicate don't bleed into the other.
        import copy as _copy
        dup = _copy.deepcopy(self.profiles[old])
        # V14.10.0: the duplicate must NOT inherit the original's sticky
        # shortcut number -- drop it so the next refresh assigns the
        # lowest free number to the copy while the original keeps its own.
        dup.pop("shortcut_number", None)
        self.profiles[candidate] = dup
        self._ensure_visible(candidate)
        self._persist(f"Duplicated: {candidate}")
        self._refresh_list()
        self._select_by_name(candidate)

    def _delete_selected(self):
        name = self._selected_name()
        if not name or name not in self.profiles:
            return
        r = QMessageBox.question(self, "Delete",
                                 f"Delete profile '{name}'?",
                                 QMessageBox.StandardButton.Yes
                                 | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        self._push_undo()
        del self.profiles[name]
        # V11.3 fix (audit A3): also wipe the on-disk asset folder and
        # the rotation counter — the equivalent of what main_window's
        # _delete_profile does. Without this the assets folder leaks
        # in %APPDATA% forever.
        try:
            from .profile_assets import (
                delete_profile_assets, rotation_key_for,
            )
            delete_profile_assets(name)
            self.main.settings.remove(rotation_key_for(name))
        except Exception:
            pass
        # V11.5 fix (audit B2): every queue row pinned to the deleted
        # profile must drop back to NO_PROFILE. main_window._delete_profile
        # already handles this for header-bar deletes; mirror it here so
        # both code paths behave the same.
        try:
            self.main._rebase_queue_rows(deleted={name})
        except Exception:
            pass
        self._persist(f"Deleted profile: {name}")
        self._refresh_list()

    # ---- import / export ---------------------------------------

    def _import(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Import Profile(s)",
            self.main.settings.value("last_profile_dir", ""),
            "Veloxa Video Editor Profile (*.vvprof *.json);;All Files (*.*)")
        if not f:
            return
        self.main.settings.setValue("last_profile_dir", str(Path(f).parent))
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Import Failed",
                                 f"Could not read file:\n{e}")
            return

        candidates = {}
        if isinstance(data, dict):
            if isinstance(data.get("profiles"), dict):
                candidates = {str(k): v for k, v in data["profiles"].items()
                              if isinstance(v, dict)}
            elif "name" in data and isinstance(data.get("settings"), dict):
                candidates = {str(data["name"]): data["settings"]}
            elif data and all(isinstance(v, dict) for v in data.values()):
                candidates = {str(k): v for k, v in data.items()}
        if not candidates:
            QMessageBox.critical(self, "Import Failed",
                                 "Unrecognized file format.")
            return

        added = 0
        skipped = 0
        # One undo entry covers the whole import operation.
        snapshotted = False
        for name, settings in candidates.items():
            target = name
            if target in self.profiles:
                r = QMessageBox.question(
                    self, "Profile Exists",
                    f"'{target}' already exists. Overwrite?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No
                    | QMessageBox.StandardButton.Cancel)
                if r == QMessageBox.StandardButton.Cancel:
                    break
                if r != QMessageBox.StandardButton.Yes:
                    skipped += 1
                    continue
            if not snapshotted:
                self._push_undo()
                snapshotted = True
            # V14.10.0: an imported profile keeps its shortcut number
            # only if that number is free here; otherwise drop it so the
            # next refresh assigns a fresh one instead of stealing an
            # existing profile's number.
            if isinstance(settings, dict):
                n = settings.get("shortcut_number")
                holder = (self.main._profile_by_number(n)
                          if isinstance(n, int) else None)
                if holder and holder != target:
                    settings.pop("shortcut_number", None)
            self.profiles[target] = settings
            added += 1

        if added:
            # If the search filter would hide everything we just imported,
            # clear it so the user can actually see them.
            if self._search_text:
                hidden = sum(1 for n in candidates
                             if self._search_text not in n.lower())
                if hidden == len(candidates):
                    self.search_box.blockSignals(True)
                    self.search_box.setText("")
                    self.search_box.blockSignals(False)
                    self._search_text = ""
            self._persist(f"Imported {added} profile(s)")
            self._refresh_list()
        QMessageBox.information(
            self, "Import",
            f"Imported {added} profile(s)."
            + (f"\nSkipped {skipped}." if skipped else ""))

    def _export_selected(self):
        name = self._selected_name()
        if not name or name not in self.profiles:
            QMessageBox.information(self, "Export",
                                    "Select a profile to export.")
            return
        last_dir = self.main.settings.value("last_profile_dir", "")
        suggested = (str(Path(last_dir) / f"{name}.vvprof") if last_dir
                     else f"{name}.vvprof")
        f, _ = QFileDialog.getSaveFileName(
            self, "Export Profile", suggested,
            "Veloxa Video Editor Profile (*.vvprof);;JSON (*.json)")
        if not f:
            return
        self.main.settings.setValue("last_profile_dir", str(Path(f).parent))
        payload = {"veloxa_version": "V11", "name": name,
                   "settings": self.profiles[name]}
        try:
            with open(f, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, indent=2)
        except OSError as e:
            QMessageBox.critical(self, "Export Failed",
                                 f"Could not write file:\n{e}")
            return
        QMessageBox.information(self, "Export",
                                f"Exported '{name}' to:\n{f}")

    def _export_all(self):
        if not self.profiles:
            QMessageBox.information(self, "Export All",
                                    "There are no profiles to export.")
            return
        last_dir = self.main.settings.value("last_profile_dir", "")
        suggested = (str(Path(last_dir) / "veloxa_profiles.vvprof") if last_dir
                     else "veloxa_profiles.vvprof")
        f, _ = QFileDialog.getSaveFileName(
            self, "Export All Profiles", suggested,
            "Veloxa Video Editor Profile (*.vvprof);;JSON (*.json)")
        if not f:
            return
        self.main.settings.setValue("last_profile_dir", str(Path(f).parent))
        payload = {"veloxa_version": "V11", "profiles": dict(self.profiles)}
        try:
            with open(f, "w", encoding="utf-8") as fp:
                json.dump(payload, fp, indent=2)
        except OSError as e:
            QMessageBox.critical(self, "Export Failed",
                                 f"Could not write file:\n{e}")
            return
        QMessageBox.information(
            self, "Export All",
            f"Exported {len(self.profiles)} profile(s) to:\n{f}")

    # ---- quick: create-from-image -------------------------------

    def _pick_quick_image(self):
        f, _ = QFileDialog.getOpenFileName(
            self, "Pick Watermark Image",
            self.main.settings.value("last_wm_dir", ""),
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*.*)")
        if f:
            self.main.settings.setValue("last_wm_dir", str(Path(f).parent))
            # Copy into the app's watermarks folder so the profile created
            # from this image stays valid even if the user moves the file.
            from .persistence import import_watermark_image
            local_path = import_watermark_image(f)
            self.quick_img_path.setText(local_path)

    def _create_from_image(self):
        img = self.quick_img_path.text().strip()
        if not img or not os.path.exists(img):
            QMessageBox.information(self, "Pick an image first",
                                    "Click 'Pick Image...' to choose a file.")
            return
        suggest = Path(img).stem
        name, ok = QInputDialog.getText(self, "Profile Name",
                                        "Name the new profile:", text=suggest)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name == NO_PROFILE:
            QMessageBox.information(self, "Reserved Name",
                                    "That name is reserved.")
            return
        if name in self.profiles:
            r = QMessageBox.question(self, "Overwrite?",
                                     f"'{name}' exists. Overwrite?")
            if r != QMessageBox.StandardButton.Yes:
                return
        settings = self.main._collect_settings_dict()
        settings["wm_path"] = img
        settings["wm_preset"] = settings.get("wm_preset") or "Bottom-Right"
        if not settings.get("wm_opacity"):
            settings["wm_opacity"] = 100
        if not settings.get("wm_scale"):
            settings["wm_scale"] = 15
        self._push_undo()
        self.main._store_profile(name, settings)
        self._ensure_visible(name)
        self._persist(f"Created profile: {name}")
        self._refresh_list()
        self._select_by_name(name)
        QMessageBox.information(
            self, "Profile Created",
            f"Created '{name}' with that image as the watermark. "
            "Click 'Load Selected' to apply it now.")

    # ---- close --------------------------------------------------

    def _load_and_close(self):
        name = self._selected_name()
        if not name:
            QMessageBox.information(self, "Load",
                                    "Select a profile to load.")
            return
        # Profiles are already mutated directly on self.main.profiles by
        # every action, so just apply the chosen one and close.
        self.main._apply_settings_dict(self.profiles[name])
        idx = self.main.profile_combo.findText(name)
        if idx >= 0:
            self.main.profile_combo.blockSignals(True)
            self.main.profile_combo.setCurrentIndex(idx)
            self.main.profile_combo.blockSignals(False)
        self.main.settings.setValue("last_profile", name)
        self.main.status_lbl.setText(f"Loaded profile: {name}")
        self.main._sync_seek_bar_trim()
        self.main._refresh_encoder_combo()
        self.main._schedule_preview()
        self.main._update_profile_button_state()
        self.accept()


# ============================================================== DraftsDialog

class DraftsDialog(QDialog):
    """V14.11.0 Save Progress: manage saved drafts.

    A draft is a full work-session snapshot (queue rows + settings). From
    here the user can resume one (open it into the window), submit it
    (open and immediately start encoding), rename it, delete it, or save
    the current session as a new draft. The auto-save toggle lives here
    too, so the setting sits next to the thing it affects.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.main = parent
        self._metas = []
        self.setWindowTitle("Saved Drafts")
        self.setMinimumSize(760, 460)

        v = QVBoxLayout(self)

        intro = QLabel(
            "A draft stores your whole session -- every queue row (with "
            "its profile and done/pending status) plus all Trim, "
            "Watermark, Audio Visuals, and Output settings. Open one to "
            "pick up exactly where you left off.")
        intro.setProperty("role", "muted")
        intro.setWordWrap(True)
        v.addWidget(intro)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Draft", "Items", "Progress", "Last saved"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection)
        self.table.setToolTip(
            "Saved drafts, most recently saved first. 'Autosave' and "
            "'Last session' are maintained automatically by Veloxa.")
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            hdr.setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._open_selected)
        self.table.itemSelectionChanged.connect(self._sync_buttons)
        v.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.open_btn = QPushButton("📂 Open")
        self.open_btn.setToolTip(
            "Load this draft into the main window -- queue and settings "
            "-- so you can keep editing it.")
        self.open_btn.clicked.connect(self._open_selected)
        row.addWidget(self.open_btn)

        self.start_btn = QPushButton("▶ Open && Start")
        self.start_btn.setObjectName("primary")
        self.start_btn.setToolTip(
            "Load this draft and immediately start encoding its pending "
            "rows. Rows already marked done are not re-encoded.")
        self.start_btn.clicked.connect(self._open_and_start)
        row.addWidget(self.start_btn)

        self.rename_btn = QPushButton("✎ Rename...")
        self.rename_btn.setToolTip(
            "Rename this draft. Auto-maintained drafts can't be renamed.")
        self.rename_btn.clicked.connect(self._rename_selected)
        row.addWidget(self.rename_btn)

        self.del_btn = QPushButton("🗑 Delete")
        self.del_btn.setObjectName("danger")
        self.del_btn.setToolTip(
            "Permanently delete this draft. Source files on disk are "
            "never touched.")
        self.del_btn.clicked.connect(self._delete_selected)
        row.addWidget(self.del_btn)

        row.addStretch()
        self.save_btn = QPushButton("💾 Save Current as New Draft")
        self.save_btn.setToolTip(
            "Save the current queue and settings as a brand-new draft.")
        self.save_btn.clicked.connect(self._save_current)
        row.addWidget(self.save_btn)
        v.addLayout(row)

        self.autosave_chk = QCheckBox(
            "Auto-save progress after each change and after each "
            "completed video")
        self.autosave_chk.setToolTip(
            "When on, progress is saved automatically whenever the queue "
            "changes and each time a video finishes encoding. It updates "
            "the draft you have open, or a rolling 'Autosave' entry when "
            "no draft is open. Turn off to save only when you click "
            "Save Progress.")
        self.autosave_chk.setChecked(self.main.is_autosave_enabled())
        self.autosave_chk.toggled.connect(self._on_autosave_toggled)
        v.addWidget(self.autosave_chk)

        bottom = QHBoxLayout()
        self.status_lbl = QLabel("")
        self.status_lbl.setProperty("role", "muted")
        self.status_lbl.setWordWrap(True)
        bottom.addWidget(self.status_lbl, 1)
        close_btn = QPushButton("✕ Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        v.addLayout(bottom)

        self._refresh()
        mirror_tooltips_to_accessibility(self)

    # ------------------------------------------------------ helpers

    def _refresh(self):
        from . import drafts as drafts_store
        metas = drafts_store.list_drafts()
        self._metas = metas
        self.table.setRowCount(len(metas))
        for r, m in enumerate(metas):
            name_item = QTableWidgetItem(drafts_store.display_name(m))
            name_item.setData(Qt.ItemDataRole.UserRole, m["id"])
            if m["id"] in drafts_store.RESERVED_IDS:
                name_item.setToolTip("Maintained automatically by Veloxa.")
            self.table.setItem(r, 0, name_item)
            self.table.setItem(r, 1, QTableWidgetItem(str(m["n_items"])))
            total = m["n_items"]
            prog = f"{m['n_done']}/{total} done" if total else "empty"
            self.table.setItem(r, 2, QTableWidgetItem(prog))
            self.table.setItem(
                r, 3,
                QTableWidgetItem((m.get("updated_at") or "").replace(
                    "T", "  ")))
        if metas:
            self.table.selectRow(0)
        self.status_lbl.setText(
            f"{len(metas)} draft(s) saved."
            if metas else "No drafts saved yet.")
        self._sync_buttons()

    def _sync_buttons(self):
        from . import drafts as drafts_store
        did = self._selected_id()
        has = did is not None
        self.open_btn.setEnabled(has)
        self.start_btn.setEnabled(has)
        self.del_btn.setEnabled(has)
        self.rename_btn.setEnabled(
            has and did not in drafts_store.RESERVED_IDS)

    def _selected_id(self):
        r = self.table.currentRow()
        if r < 0 or r >= self.table.rowCount():
            return None
        it = self.table.item(r, 0)
        if it is None:
            return None
        did = it.data(Qt.ItemDataRole.UserRole)
        return did if isinstance(did, str) else None

    # ------------------------------------------------------ actions

    def _open_selected(self):
        did = self._selected_id()
        if did and self.main.load_draft_into_window(did):
            self.accept()

    def _open_and_start(self):
        did = self._selected_id()
        if did and self.main.load_draft_into_window(did, start_after=True):
            self.accept()

    def _rename_selected(self):
        from . import drafts as drafts_store
        did = self._selected_id()
        if not did or did in drafts_store.RESERVED_IDS:
            return
        cur = drafts_store.load_draft(did) or {}
        new, ok = QInputDialog.getText(
            self, "Rename Draft", "New name:", text=cur.get("name", ""))
        if not ok or not new.strip():
            return
        if drafts_store.rename_draft(did, new.strip()):
            if self.main._current_draft_id == did:
                self.main._set_current_draft(did, new.strip())
            self._refresh()

    def _delete_selected(self):
        from . import drafts as drafts_store
        did = self._selected_id()
        if not did:
            return
        meta = next((m for m in self._metas if m["id"] == did), {})
        label = drafts_store.display_name(meta) if meta else did
        r = QMessageBox.question(
            self, "Delete Draft",
            f"Delete the draft '{label}'?\n\n"
            "This only removes the saved draft -- your video files on "
            "disk are not touched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        if drafts_store.delete_draft(did):
            if self.main._current_draft_id == did:
                self.main._set_current_draft("", "")
            self._refresh()
        else:
            QMessageBox.warning(self, "Delete Draft",
                                "Could not delete that draft file.")

    def _save_current(self):
        if self.main.save_progress(ask_name=True):
            self._refresh()

    def _on_autosave_toggled(self, on: bool):
        self.main.set_autosave_enabled(on)
        self.status_lbl.setText(
            "Auto-save is ON -- progress saves after each change and "
            "each completed video."
            if on else
            "Auto-save is OFF -- use Save Progress to save manually.")
