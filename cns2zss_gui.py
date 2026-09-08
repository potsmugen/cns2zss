#!/usr/bin/env python3
# cns2zss_gui.py - GUI for batch conversion of CNS/ST files to ZSS.
# Requires cns2zss.py in the same folder.

import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

from cns2zss import convert_cns_to_zss, read_file_with_encoding


class CNS2ZSSApp:
    def __init__(self, root):
        self.root = root
        root.title("CNS to ZSS Converter GUI")
        root.geometry("750x550")

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

        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except Exception as error:
            messagebox.showerror(
                "Error",
                f"Could not open folder: {error}"
            )

    def log(self, msg):
        # Schedule on main thread so it's safe to call from worker threads
        self.root.after(0, self._log_impl, msg)

    def _log_impl(self, msg):
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)

    def convert_files(self, use_selection):
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

        self.convert_sel_btn.config(state='disabled')
        self.convert_all_btn.config(state='disabled')
        self.log(f"Starting conversion of {len(approved)} file(s)...")

        # Run the heavy work off the UI thread
        thread = threading.Thread(
            target=self._convert_worker,
            args=(approved,),
            daemon=True
        )
        thread.start()

    def _convert_worker(self, paths):
        success = 0

        for filepath in paths:
            outpath = filepath + ".zss"
            self.log(f"Processing: {os.path.basename(filepath)}")

            try:
                data, _ = read_file_with_encoding(filepath)
                zss_data = convert_cns_to_zss(data)

                if zss_data == '(NO_STATEDDEF)':
                    self.log(
                        "  -> Skipped: no [Statedef] found, "
                        "file left unchanged."
                    )
                else:
                    with open(outpath, 'w', encoding='utf-8') as file:
                        file.write(zss_data)

                    self.log(f"  -> Saved: {outpath}")
                    success += 1

            except Exception as error:
                self.log(f"  ERROR: {error}")

        # Hand control back to the main thread for UI updates
        self.root.after(
            0,
            self._convert_done,
            success,
            len(paths)
        )

    def _convert_done(self, success, total):
        self.log(f"Done. {success} of {total} files converted.")

        self.convert_sel_btn.config(state='normal')
        self.convert_all_btn.config(state='normal')

        messagebox.showinfo(
            "Batch Conversion",
            f"Converted {success} of {total} files."
        )


if __name__ == "__main__":
    root = tk.Tk()
    app = CNS2ZSSApp(root)
    root.mainloop()
