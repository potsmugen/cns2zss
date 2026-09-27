#!/usr/bin/env python3
# cns2zss_gui.py - GUI for batch conversion of CNS/ST files to ZSS.
# Requires cns2zss.py in the same folder.

import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from cns2zss import (
    convert_cns_to_zss,
    read_file_with_encoding,
    write_file_atomically,
)


def resource_path(relative_path):
    """Return a resource path that works from source and PyInstaller builds."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class CNS2ZSSApp:
    def __init__(self, root):
        self.root = root
        self.cancel_event = threading.Event()
        self.conversion_active = False
        self.worker_thread = None
        self.close_when_done = False
        root.title("CNS to ZSS Converter")
        root.geometry("750x550")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if sys.platform == "win32":
            root.iconbitmap(resource_path(os.path.join("assets", "icon.ico")))
        else:
            self.window_icon = tk.PhotoImage(
                file=resource_path(os.path.join("assets", "icon.png"))
            )
            root.iconphoto(True, self.window_icon)

        # File selection
        tk.Label(
            root,
            text="Select CNS files to convert:"
        ).pack(anchor='w', padx=5, pady=2)

        self.file_listbox = tk.Listbox(
            root,
            selectmode=tk.EXTENDED,
            height=6
        )
        self.file_listbox.pack(fill='x', padx=5, pady=2)
        self.file_listbox.bind("<Double-Button-1>", self.open_input_file)

        # Button row - centered
        btn_frame = tk.Frame(root)
        btn_frame.pack(anchor='center', pady=2)

        tk.Button(
            btn_frame,
            text="Add Files",
            command=self.add_files
        ).pack(side='left', padx=2)

        tk.Button(
            btn_frame,
            text="Remove Selected",
            command=self.remove_selected
        ).pack(side='left', padx=2)

        tk.Button(
            btn_frame,
            text="Clear All",
            command=self.clear_all
        ).pack(side='left', padx=2)

        tk.Button(
            btn_frame,
            text="Open File Location",
            command=self.open_location
        ).pack(side='left', padx=2)

        # Convert buttons
        convert_frame = tk.Frame(root)
        convert_frame.pack(pady=10)

        self.convert_sel_btn = tk.Button(
            convert_frame,
            text="Convert Selected",
            command=lambda: self.convert_files(use_selection=True)
        )
        self.convert_sel_btn.pack(side='left', padx=5)

        self.convert_all_btn = tk.Button(
            convert_frame,
            text="Convert All",
            command=lambda: self.convert_files(use_selection=False)
        )
        self.convert_all_btn.pack(side='left', padx=5)

        self.cancel_btn = tk.Button(
            convert_frame,
            text="Cancel Batch",
            command=self.cancel_conversion,
            state='disabled'
        )
        self.cancel_btn.pack(side='left', padx=5)

        # Off drops warnings and code the engine ignores; `:=` warnings stay.
        self.keep_warnings = tk.BooleanVar(value=True)
        tk.Checkbutton(
            root,
            text="Keep warnings as commented code",
            variable=self.keep_warnings
        ).pack()

        # Log area
        tk.Label(
            root,
            text="Conversion log:"
        ).pack(anchor='w', padx=5)

        self.log_text = scrolledtext.ScrolledText(
            root,
            wrap=tk.WORD,
            height=15
        )
        self.log_text.pack(
            fill='both',
            expand=True,
            padx=5,
            pady=2
        )

        # Clear Log button under the log window
        tk.Button(
            root,
            text="Clear Log",
            command=self.clear_log
        ).pack(pady=2)

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Select CNS files",
            filetypes=[
                ("Mugen extensions", "*.cns *.cmd *.st"),
                ("All files", "*.*")
            ]
        )

        for path in paths:
            if path not in self.file_listbox.get(0, tk.END):
                self.file_listbox.insert(tk.END, path)

    def remove_selected(self):
        selected = self.file_listbox.curselection()

        for idx in reversed(selected):
            self.file_listbox.delete(idx)

    def clear_all(self):
        self.file_listbox.delete(0, tk.END)

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def open_input_file(self, event):
        """Open the double-clicked input file with its default application."""
        index = self.file_listbox.nearest(event.y)
        row = self.file_listbox.bbox(index)
        if row is None or not row[1] <= event.y < row[1] + row[3]:
            return "break"

        filepath = self.file_listbox.get(index)
        if not os.path.isfile(filepath):
            messagebox.showerror("Error", f"File does not exist: {filepath}")
            return "break"

        self._open_with_default_app(filepath, "file")
        return "break"

    def _open_with_default_app(self, path, description):
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as error:
            messagebox.showerror(
                "Error",
                f"Could not open {description}: {error}"
            )

    def open_location(self):
        """Open the OS file browser at the folder of the selected file."""
        selection = self.file_listbox.curselection()

        if not selection:
            messagebox.showwarning(
                "No selection",
                "Please select a file first."
            )
            return

        filepath = self.file_listbox.get(selection[0])
        folder = os.path.dirname(os.path.abspath(filepath))

        if not os.path.exists(folder):
            messagebox.showerror(
                "Error",
                f"Folder does not exist: {folder}"
            )
            return

        self._open_with_default_app(folder, "folder")

    def log(self, msg):
        # Schedule on main thread so it's safe to call from worker threads
        self.root.after(0, self._log_impl, msg)

    def _log_impl(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)

    def convert_files(self, use_selection):
        if self.conversion_active:
            return

        if use_selection:
            selected = self.file_listbox.curselection()

            if not selected:
                messagebox.showwarning(
                    "No selection",
                    "Please select at least one file."
                )
                return

            paths = [
                self.file_listbox.get(i)
                for i in selected
            ]
        else:
            paths = list(self.file_listbox.get(0, tk.END))

            if not paths:
                messagebox.showwarning(
                    "No files",
                    "Please add at least one file."
                )
                return

        # Pre-confirm overwrites on the main thread
        approved = []

        for filepath in paths:
            outpath = filepath + ".zss"

            if os.path.exists(outpath):
                answer = messagebox.askyesnocancel(
                    "File exists",
                    f"{os.path.basename(outpath)} already exists.\n"
                    "Overwrite?",
                    icon='warning'
                )

                if answer is None:
                    self.log("Conversion cancelled by user.")
                    return
                elif answer:
                    approved.append(filepath)
            else:
                approved.append(filepath)

        if not approved:
            self.log("Nothing to convert (all skipped or cancelled).")
            return

        self.cancel_event.clear()
        self.conversion_active = True
        self.convert_sel_btn.config(state='disabled')
        self.convert_all_btn.config(state='disabled')
        self.cancel_btn.config(state='normal')
        self.log(f"Starting conversion of {len(approved)} file(s)...")

        # Run the heavy work off the UI thread
        self.worker_thread = threading.Thread(
            target=self._convert_worker,
            args=(approved, self.keep_warnings.get()),
            daemon=True
        )
        self.worker_thread.start()

    def cancel_conversion(self):
        if not self.conversion_active or self.cancel_event.is_set():
            return

        if self.worker_thread is not None and not self.worker_thread.is_alive():
            return

        self.cancel_event.set()
        self.cancel_btn.config(state='disabled')
        self.log("Cancellation requested; finishing the current file...")

    def on_close(self):
        if not self.conversion_active:
            self.root.destroy()
            return

        close_after_cancel = messagebox.askyesno(
            "Conversion in progress",
            "Cancel the batch and close after the current file finishes?",
            parent=self.root
        )
        if close_after_cancel:
            self.close_when_done = True
            self.cancel_conversion()

    def _convert_worker(self, paths, keep_warnings=True):
        converted = 0
        skipped = 0
        failed = 0
        cancelled = False

        for filepath in paths:
            if self.cancel_event.is_set():
                cancelled = True
                break

            outpath = filepath + ".zss"
            self.log(f"Processing: {os.path.basename(filepath)}")

            try:
                data, _ = read_file_with_encoding(filepath)
                warnings = []
                zss_data = convert_cns_to_zss(data, keep_warnings, warnings)

                if zss_data == '(NO_STATEDDEF)':
                    self.log(
                        "  -> Skipped: no [Statedef] found, "
                        "file left unchanged."
                    )
                    skipped += 1
                else:
                    write_file_atomically(outpath, zss_data)
                    self.log(f"  -> Saved: {outpath}")

                    for warning in warnings:
                        self.log(f"  WARNING: {warning}")
                    converted += 1

            except Exception as error:
                self.log(f"  ERROR: {error}")
                failed += 1

        # Hand control back to the main thread for UI updates
        self.root.after(
            0,
            self._convert_done,
            converted,
            skipped,
            failed,
            len(paths),
            cancelled
        )

    def _convert_done(self, converted, skipped, failed, total, cancelled):
        status = "Cancelled" if cancelled else "Done"
        summary = (
            f"{status}. Converted: {converted}; skipped: {skipped}; "
            f"failed: {failed}"
        )
        if cancelled:
            not_started = total - converted - skipped - failed
            summary += f"; not started: {not_started}"
        summary += f" (of {total} file(s))."
        self.log(summary)

        self.conversion_active = False
        self.worker_thread = None
        self.convert_sel_btn.config(state='normal')
        self.convert_all_btn.config(state='normal')
        self.cancel_btn.config(state='disabled')

        if self.close_when_done:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = CNS2ZSSApp(root)
    root.mainloop()
