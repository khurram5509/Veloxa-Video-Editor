"""Profile manager and simple HTML info-dialog helpers."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout,
)


NO_PROFILE = "(no profile)"


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
        existing = parent.settings.value("watch_folder", "")
        if existing:
            self.folder_path.setText(existing)
        row.addWidget(self.folder_path, 1)
        browse = QPushButton("📂 Browse...")
        browse.clicked.connect(self._pick_folder)
        row.addWidget(browse)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Move processed files to subfolder:"))
        self.done_subfolder = QLineEdit(
            parent.settings.value("watch_done_subfolder", "done"))
        self.done_subfolder.setMaxLength(64)
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
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("■ Stop")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.clicked.connect(self._on_stop)
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(self.start_btn)
        bottom.addWidget(self.stop_btn)
        bottom.addWidget(close_btn)
        v.addLayout(bottom)

        self._refresh_state()

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
        self.refresh_btn.clicked.connect(self._refresh)
        row.addWidget(self.refresh_btn)
        self.open_btn = QPushButton("📂 Open Folder")
        self.open_btn.clicked.connect(self._open_folder)
        row.addWidget(self.open_btn)
        row.addStretch()
        self.del_one_btn = QPushButton("🗑 Delete Selected")
        self.del_one_btn.clicked.connect(self._delete_selected)
        row.addWidget(self.del_one_btn)
        self.del_all_btn = QPushButton("🗑 Delete ALL")
        self.del_all_btn.setObjectName("danger")
        self.del_all_btn.clicked.connect(self._delete_all)
        row.addWidget(self.del_all_btn)
        close_btn = QPushButton("✕ Close")
        close_btn.setObjectName("primary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        v.addLayout(row)

        self._refresh()

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
        dup_btn = QPushButton("⎘ Duplicate")
        dup_btn.setToolTip("Duplicate the selected profile (Ctrl+D)")
        dup_btn.clicked.connect(self._duplicate_selected)
        del_btn = QPushButton("🗑 Delete")
        del_btn.setObjectName("danger")
        del_btn.setToolTip("Delete the selected profile (Delete)")
        del_btn.clicked.connect(self._delete_selected)
        row1.addWidget(new_btn); row1.addWidget(edit_btn)
        row1.addWidget(rename_btn); row1.addWidget(dup_btn)
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
        pick_btn = QPushButton("📂 Pick Image...")
        pick_btn.clicked.connect(self._pick_quick_image)
        create_btn = QPushButton("＋ Create Profile")
        create_btn.setObjectName("primary")
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
            self.list.addItem(name)
        self.list.blockSignals(False)
        if prev and prev in self.profiles and self._is_in_list(prev):
            self._select_by_name(prev)
        elif self.list.count() > 0:
            self.list.setCurrentRow(0)
        self._on_selection_changed()

    def _is_in_list(self, name: str) -> bool:
        for i in range(self.list.count()):
            if self.list.item(i).text() == name:
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
        return item.text() if item else None

    def _select_by_name(self, name: str):
        for i in range(self.list.count()):
            if self.list.item(i).text() == name:
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
        self.profiles[name] = self.main._collect_settings_dict()
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
        self.profiles[candidate] = _copy.deepcopy(self.profiles[old])
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
        self.profiles[name] = settings
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
