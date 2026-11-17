"""Tkinter settings window. Uses only openremap.service (no backend imports)."""
import functools
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from ...service import ApiError, RemapService

PAD = 6


class _Handled(Exception):
    """Raised after an ApiError was already shown to the user."""


def api(parent, fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ApiError as e:
        messagebox.showerror("OpenRemap", e.message, parent=parent.winfo_toplevel())
        raise _Handled()


def guarded(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except _Handled:
            return None
    return wrapper


def scrolled_tree(parent, columns, headings, widths):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
    for i, (col, head, width) in enumerate(zip(columns, headings, widths)):
        tree.heading(col, text=head)
        tree.column(col, width=width, stretch=(i == len(columns) - 1))
    sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    tree.tag_configure("dim", foreground="gray50")
    return frame, tree


class Modal(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())

    def show(self):
        self.update_idletasks()
        top = self.master.winfo_toplevel()
        x = top.winfo_rootx() + max(0, (top.winfo_width() - self.winfo_reqwidth()) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry("+%d+%d" % (x, y))
        self.deiconify()
        self.grab_set()
        self.wait_window()
        return self.result

    def cancel(self):
        self.result = None
        self.destroy()


# ---------------------------------------------------------------- dialogs ----

class ActionDialog(Modal):
    """Generic editor built from service.action_types() metadata."""

    def __init__(self, parent, service, key, action, is_default):
        super().__init__(parent, "Set %s" % key)
        self.service = service
        self.resizable(False, False)
        self.types = service.action_types()
        first = "Not set" if is_default else "Inherit from Default"
        self.choices = [(first, None)] + [(t["label"], t["type"]) for t in self.types]
        self.vars = {}

        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="When %s is pressed:" % key).grid(row=0, column=0, sticky="w")
        self.choice = tk.StringVar()
        box = ttk.Combobox(body, textvariable=self.choice, state="readonly", width=30,
                           values=[c[0] for c in self.choices])
        box.grid(row=0, column=1, sticky="ew", padx=(PAD, 0))
        box.bind("<<ComboboxSelected>>", lambda e: self._build_fields({}))
        self.help_var = tk.StringVar()
        ttk.Label(body, textvariable=self.help_var, foreground="gray35", wraplength=420).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(PAD, 0))
        self.fields = ttk.Frame(body)
        self.fields.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(PAD, 0))

        btns = ttk.Frame(body)
        btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="OK", command=self.ok, default="active").pack(side="left")
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="left", padx=(PAD, 0))
        self.bind("<Return>", lambda e: self.ok())

        current = (action or {}).get("type")
        self.choice.set(next((label for label, t in self.choices if t == current), first))
        self._build_fields(action or {})

    def _type(self):
        return dict(self.choices).get(self.choice.get())

    def _build_fields(self, prefill):
        for w in self.fields.winfo_children():
            w.destroy()
        self.vars = {}
        kind = self._type()
        if kind is None:
            self.help_var.set("Clears this key in this profile.")
            return
        spec = next(t for t in self.types if t["type"] == kind)
        self.help_var.set(spec.get("help", ""))
        row = 0
        first_entry = None
        for f in spec["fields"]:
            value = prefill.get(f["name"], f.get("default"))
            if f["kind"] == "bool":
                var = tk.BooleanVar(value=bool(value))
                ttk.Checkbutton(self.fields, text=f["label"], variable=var).grid(
                    row=row, column=0, columnspan=3, sticky="w", pady=(PAD, 0))
            else:
                if isinstance(value, list):
                    value = "+".join(value)
                var = tk.StringVar(value=value or "")
                ttk.Label(self.fields, text=f["label"] + ":").grid(row=row, column=0, sticky="w", pady=(PAD, 0))
                entry = ttk.Entry(self.fields, textvariable=var, width=44)
                entry.grid(row=row, column=1, sticky="ew", padx=(PAD, 0), pady=(PAD, 0))
                first_entry = first_entry or entry
                if f["kind"] == "command":
                    ttk.Button(self.fields, text="Browse...",
                               command=lambda v=var: self._browse(v)).grid(row=row, column=2, padx=(PAD, 0), pady=(PAD, 0))
                if f.get("hint"):
                    row += 1
                    ttk.Label(self.fields, text=f["hint"], foreground="gray45").grid(row=row, column=1, sticky="w", padx=(PAD, 0))
            self.vars[f["name"]] = var
            row += 1
        if first_entry:
            first_entry.focus_set()

    def _browse(self, var):
        path = filedialog.askopenfilename(parent=self, title="Choose a program or file")
        if path:
            var.set('"%s"' % path if " " in path else path)

    def ok(self):
        kind = self._type()
        if kind is None:
            self.result = ("clear", None)
            self.destroy()
            return
        action = {"type": kind}
        action.update({name: var.get() for name, var in self.vars.items()})
        try:
            action = self.service.validate_action(action)
        except ApiError as e:
            messagebox.showerror("Check the action", e.message, parent=self)
            return
        self.result = ("set", action)
        self.destroy()


class AppsDialog(Modal):
    def __init__(self, parent, service, profile_name, apps):
        super().__init__(parent, "Apps for %s" % profile_name)
        self.service = service
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="This profile is used while one of these programs is in the foreground.",
                  wraplength=380).pack(anchor="w")
        self.listbox = tk.Listbox(body, height=8, width=44)
        self.listbox.pack(fill="both", expand=True, pady=PAD)
        for a in apps:
            self.listbox.insert("end", a)

        row = ttk.Frame(body)
        row.pack(fill="x")
        self.entry_var = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.entry_var)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda e: (self.add(), "break")[1])
        ttk.Button(row, text="Add", command=self.add).pack(side="left", padx=(PAD, 0))
        ttk.Button(row, text="Remove", command=self.remove).pack(side="left", padx=(PAD, 0))
        ttk.Label(body, text="Exe names, e.g. chrome.exe, msrdc.exe (Remote Desktop / AVD)",
                  foreground="gray45").pack(anchor="w")

        det = ttk.Frame(body)
        det.pack(fill="x", pady=(PAD, 0))
        self.detect_btn = ttk.Button(det, text="Detect app", command=self.detect)
        self.detect_btn.pack(side="left")
        self.detect_var = tk.StringVar(value="Click, then switch to the app within 3 seconds.")
        ttk.Label(det, textvariable=self.detect_var, foreground="gray35").pack(side="left", padx=(PAD, 0))

        btns = ttk.Frame(body)
        btns.pack(anchor="e", pady=(12, 0))
        ttk.Button(btns, text="OK", command=self.ok).pack(side="left")
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="left", padx=(PAD, 0))
        entry.focus_set()

    def _items(self):
        return list(self.listbox.get(0, "end"))

    def add(self, name=None):
        name = (name or self.entry_var.get()).strip().strip('"')
        if name and name.lower() not in [a.lower() for a in self._items()]:
            self.listbox.insert("end", name.lower())
        self.entry_var.set("")

    def remove(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)

    def detect(self, remaining=3):
        if remaining == 3:
            self.detect_btn.state(["disabled"])
        if remaining > 0:
            self.detect_var.set("Switch to the app now... %d" % remaining)
            self.after(1000, self.detect, remaining - 1)
            return
        self.detect_btn.state(["!disabled"])
        app = self.service.foreground_app()
        if not app:
            self.detect_var.set("Couldn't detect the app (supported on Windows only).")
        elif app in ("python.exe", "pythonw.exe"):
            self.detect_var.set("That was this window. Click Detect, then switch to the app.")
        else:
            self.add(app)
            self.detect_var.set("Added %s." % app)

    def ok(self):
        self.result = self._items()
        self.destroy()


class LearnWizard(Modal):
    POLL_MS = 60

    def __init__(self, parent, service):
        super().__init__(parent, "Learn a new device")
        self.service = service
        self.session = None
        self.saved = None
        self._captures = []
        self.minsize(520, 460)
        body = ttk.Frame(self, padding=12)
        body.pack(fill="both", expand=True)

        step1 = ttk.LabelFrame(body, text="1. Choose the keyboard", padding=PAD)
        step1.pack(fill="x")
        self.hid_var = tk.StringVar()
        self.hid_box = ttk.Combobox(step1, textvariable=self.hid_var, state="readonly", width=56)
        self.hid_box.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.hid_box.bind("<<ComboboxSelected>>", lambda e: self._suggest_name())
        self.refresh_btn = ttk.Button(step1, text="Refresh", command=self.load_hid)
        self.refresh_btn.grid(row=0, column=2, padx=(PAD, 0))
        ttk.Label(step1, text="Profile name:").grid(row=1, column=0, sticky="w", pady=(PAD, 0))
        self.name_var = tk.StringVar()
        ttk.Entry(step1, textvariable=self.name_var).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(PAD, 0), pady=(PAD, 0))
        self.start_btn = ttk.Button(step1, text="Start listening", command=self.start)
        self.start_btn.grid(row=2, column=0, columnspan=3, sticky="w", pady=(PAD, 0))
        step1.columnconfigure(1, weight=1)

        step2 = ttk.LabelFrame(body, text="2. Press each extra key once, in order", padding=PAD)
        step2.pack(fill="both", expand=True, pady=(PAD, 0))
        self.phase_var = tk.StringVar(value="Pick the keyboard and click Start listening.")
        ttk.Label(step2, textvariable=self.phase_var, wraplength=480, font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.msg_var = tk.StringVar()
        ttk.Label(step2, textvariable=self.msg_var, foreground="gray35", wraplength=480).pack(anchor="w")
        nrow = ttk.Frame(step2)
        nrow.pack(fill="x", pady=(PAD, 0))
        ttk.Label(nrow, text="Name for the next key:").pack(side="left")
        self.next_var = tk.StringVar(value="G1")
        self.next_entry = ttk.Entry(nrow, textvariable=self.next_var, width=12)
        self.next_entry.pack(side="left", padx=(PAD, 0))
        self.next_entry.bind("<KeyRelease>", lambda e: self._push_next_name())
        self.listbox = tk.Listbox(step2, height=8)
        self.listbox.pack(fill="both", expand=True, pady=(PAD, 0))
        self.listbox.bind("<Double-1>", lambda e: self.rename())
        krow = ttk.Frame(step2)
        krow.pack(fill="x", pady=(PAD, 0))
        ttk.Button(krow, text="Rename...", command=self.rename).pack(side="left")
        ttk.Button(krow, text="Remove", command=self.remove).pack(side="left", padx=(PAD, 0))

        btns = ttk.Frame(body)
        btns.pack(anchor="e", pady=(12, 0))
        self.save_btn = ttk.Button(btns, text="Save profile", command=self.save, state="disabled")
        self.save_btn.pack(side="left")
        ttk.Button(btns, text="Close", command=self.cancel).pack(side="left", padx=(PAD, 0))

        self._paused_by_us = False
        self.load_hid()

    @guarded
    def load_hid(self):
        self._hid = api(self, self.service.list_hid_devices)
        self.hid_box["values"] = [d["label"] for d in self._hid]
        if self._hid and self.hid_box.current() < 0:
            self.hid_box.current(0)
            self._suggest_name()

    def _suggest_name(self):
        idx = self.hid_box.current()
        if idx >= 0:
            self.name_var.set(self._hid[idx]["product"])

    @guarded
    def start(self):
        idx = self.hid_box.current()
        if idx < 0:
            return
        dev = self._hid[idx]
        status = self.service.engine_status()
        if not status["paused"]:  # stop the engine firing actions while we learn
            self.service.set_paused(True)
            self._paused_by_us = True
        snap = api(self, self.service.start_learning, dev["vid"], dev["pid"], dev["product"])
        self.session = snap["session"]
        for w in (self.hid_box, self.refresh_btn, self.start_btn):
            w.state(["disabled"])
        self.poll()

    def poll(self):
        if not self.session or not self.winfo_exists():
            return
        try:
            snap = self.service.learn_poll(self.session)
        except ApiError as e:
            self.phase_var.set(e.message)
            return
        if snap["phase"] == "error":
            self.phase_var.set(snap["error"])
        elif snap["phase"] == "quiet":
            self.phase_var.set("Hands off the keyboard for a moment...")
        else:
            self.phase_var.set("Listening. Press the key you want to call %s." % snap["next_name"])
        for ev in snap["events"]:
            self.msg_var.set(ev["message"])
        if self.focus_get() is not self.next_entry and self.next_var.get() != snap["next_name"]:
            self.next_var.set(snap["next_name"])
        if snap["captures"] != self._captures:
            self._captures = snap["captures"]
            self.listbox.delete(0, "end")
            for c in self._captures:
                self.listbox.insert("end", "%-8s byte %d, bit 0x%02X   (usage page 0x%04X, interface %s)" % (
                    c["name"], c["byte"], c["mask"], c["iface"]["usage_page"], c["iface"]["interface"]))
            self.save_btn.state(["!disabled"] if self._captures else ["disabled"])
        self.after(self.POLL_MS, self.poll)

    def _push_next_name(self):
        if self.session:
            self.service.learn_set_next_name(self.session, self.next_var.get())

    def _selected(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else None

    @guarded
    def rename(self):
        i = self._selected()
        if i is None or not self.session:
            return
        name = simpledialog.askstring("Rename key", "Key name:", initialvalue=self._captures[i]["name"], parent=self)
        if name:
            api(self, self.service.learn_rename_key, self.session, i, name)

    @guarded
    def remove(self):
        i = self._selected()
        if i is not None and self.session:
            api(self, self.service.learn_remove_key, self.session, i)

    @guarded
    def save(self):
        name = self.name_var.get().strip()
        try:
            dev = self.service.save_learned_device(self.session, name)
        except ApiError as e:
            if e.code != "exists":
                messagebox.showerror("OpenRemap", e.message, parent=self)
                return
            if not messagebox.askyesno("Replace profile?", e.message, parent=self):
                return
            dev = api(self, self.service.save_learned_device, self.session, name, True)
        self.saved = dev
        messagebox.showinfo("Saved", "Saved %s with %d key(s).\nAssign actions in the Bindings tab." % (
            dev["name"], len(dev["keys"])), parent=self)
        self.cancel()

    def cancel(self):
        if self.session:
            self.service.stop_learning(self.session)
            self.session = None
        if self._paused_by_us:
            self.service.set_paused(False)
        self.result = self.saved
        self.destroy()


# ------------------------------------------------------------------ tabs ----

class BindingsTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=PAD)
        self.app = app
        self.service = app.service
        self._profiles, self._devices, self._rows = [], [], {}

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Profile:", width=9).pack(side="left")
        self.profile_var = tk.StringVar()
        self.profile_box = ttk.Combobox(top, textvariable=self.profile_var, state="readonly", width=28)
        self.profile_box.pack(side="left")
        self.profile_box.bind("<<ComboboxSelected>>", lambda e: self.on_profile())
        for text, cmd in (("New...", self.new_profile), ("Rename...", self.rename_profile), ("Delete", self.delete_profile)):
            ttk.Button(top, text=text, command=cmd).pack(side="left", padx=(PAD, 0))

        apps = ttk.Frame(self)
        apps.pack(fill="x", pady=(PAD, 0))
        ttk.Label(apps, text="Active in:", width=9).pack(side="left")
        self.apps_var = tk.StringVar()
        ttk.Label(apps, textvariable=self.apps_var, foreground="gray30").pack(side="left")
        self.apps_btn = ttk.Button(apps, text="Edit apps...", command=self.edit_apps)
        self.apps_btn.pack(side="right")

        dev = ttk.Frame(self)
        dev.pack(fill="x", pady=(PAD, 0))
        ttk.Label(dev, text="Device:", width=9).pack(side="left")
        self.device_box = ttk.Combobox(dev, state="readonly", width=48)
        self.device_box.pack(side="left")
        self.device_box.bind("<<ComboboxSelected>>", lambda e: self.refresh_keys())

        frame, self.tree = scrolled_tree(self, ("key", "action"), ("Key", "Action"), (110, 480))
        frame.pack(fill="both", expand=True, pady=(PAD, 0))
        self.tree.bind("<Double-1>", lambda e: self.edit())
        self.tree.bind("<Return>", lambda e: self.edit())
        self.tree.bind("<Delete>", lambda e: self.clear())

        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(PAD, 0))
        ttk.Button(btns, text="Edit...", command=self.edit).pack(side="left")
        ttk.Button(btns, text="Clear", command=self.clear).pack(side="left", padx=(PAD, 0))
        ttk.Label(btns, text="Grey rows come from the Default profile or aren't set.",
                  foreground="gray45").pack(side="right")

    # ---- data ---------------------------------------------------------------
    def profile(self):
        return next((p for p in self._profiles if p["name"] == self.profile_var.get()), None)

    def device(self):
        idx = self.device_box.current()
        return self._devices[idx] if 0 <= idx < len(self._devices) else None

    @guarded
    def refresh_profiles(self, select=None):
        self._profiles = api(self, self.service.list_profiles)
        names = [p["name"] for p in self._profiles]
        self.profile_box["values"] = names
        if select in names:
            self.profile_var.set(select)
        elif self.profile_var.get() not in names:
            self.profile_var.set(names[0])
        self.on_profile()

    def on_profile(self):
        p = self.profile()
        if p is None:
            return
        if p["is_default"]:
            self.apps_var.set("every app (and fallback for keys other profiles leave unset)")
            self.apps_btn.state(["disabled"])
        else:
            self.apps_var.set(", ".join(p["apps"]) or "no apps yet, so this profile never activates")
            self.apps_btn.state(["!disabled"])
        self.refresh_keys()

    @guarded
    def refresh_devices(self):
        current = self.device()
        self._devices = api(self, self.service.list_devices)
        self.device_box["values"] = [
            d["name"] + ("" if d["connected"] is not False else "   (not connected)") for d in self._devices]
        if self._devices:
            ids = [d["id"] for d in self._devices]
            if current and current["id"] in ids:
                idx = ids.index(current["id"])
            else:
                idx = next((i for i, d in enumerate(self._devices) if d["connected"]), 0)
            self.device_box.current(idx)
        else:
            self.device_box.set("")
        self.refresh_keys()

    @guarded
    def refresh_keys(self, select=None):
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        dev, p = self.device(), self.profile()
        if dev is None:
            self.tree.insert("", "end", values=("", "No device profiles yet. Use the Devices tab to learn your keyboard."), tags=("dim",))
            return
        if p is None:
            return
        for row in api(self, self.service.get_bindings, p["name"], dev["id"]):
            self._rows[row["key"]] = row
            self.tree.insert("", "end", iid=row["key"], values=(row["key"], row["display"]),
                             tags=() if row["own"] else ("dim",))
        if select in self._rows:
            self.tree.selection_set(select)
            self.tree.focus(select)

    def _selected_key(self):
        sel = self.tree.selection()
        return sel[0] if sel and sel[0] in self._rows else None

    # ---- actions -------------------------------------------------------------
    @guarded
    def edit(self):
        key = self._selected_key()
        if key is None:
            return
        row, p, dev = self._rows[key], self.profile(), self.device()
        result = ActionDialog(self, self.service, key, row["action"], p["is_default"]).show()
        if result is None:
            return
        kind, action = result
        if kind == "clear":
            api(self, self.service.clear_binding, p["name"], dev["id"], key)
        else:
            api(self, self.service.set_binding, p["name"], dev["id"], key, action)
        self.app.notify("Saved %s in %s. The engine applies it automatically." % (key, p["name"]))
        self.refresh_keys(select=key)

    @guarded
    def clear(self):
        key = self._selected_key()
        if key is None or not self._rows[key]["own"]:
            return
        api(self, self.service.clear_binding, self.profile()["name"], self.device()["id"], key)
        self.app.notify("Cleared %s." % key)
        self.refresh_keys(select=key)

    @guarded
    def new_profile(self):
        name = simpledialog.askstring("New profile", "Profile name (e.g. Remote desktop, Gaming):", parent=self)
        if not name:
            return
        api(self, self.service.create_profile, name)
        self.refresh_profiles(select=name.strip())
        self.edit_apps()

    @guarded
    def rename_profile(self):
        p = self.profile()
        if p["is_default"]:
            messagebox.showinfo("OpenRemap", "The Default profile can't be renamed.", parent=self)
            return
        name = simpledialog.askstring("Rename profile", "New name:", initialvalue=p["name"], parent=self)
        if name:
            api(self, self.service.rename_profile, p["name"], name)
            self.refresh_profiles(select=name.strip())

    @guarded
    def delete_profile(self):
        p = self.profile()
        if p["is_default"]:
            messagebox.showinfo("OpenRemap", "The Default profile can't be deleted.", parent=self)
            return
        if messagebox.askyesno("Delete profile", "Delete the profile %r and its bindings?" % p["name"], parent=self):
            api(self, self.service.delete_profile, p["name"])
            self.refresh_profiles()

    @guarded
    def edit_apps(self):
        p = self.profile()
        if p is None or p["is_default"]:
            return
        apps = AppsDialog(self, self.service, p["name"], p["apps"]).show()
        if apps is None:
            return
        res = api(self, self.service.set_profile_apps, p["name"], apps)
        if res["conflicts"]:
            lines = "\n".join("%s is already used by %s" % (c["app"], c["profile"]) for c in res["conflicts"])
            messagebox.showwarning("Overlapping apps", lines + "\n\nThe first matching profile in the list wins.", parent=self)
        self.refresh_profiles(select=p["name"])


class DevicesTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=PAD)
        self.app = app
        self.service = app.service
        self._devs = []
        frame, self.tree = scrolled_tree(
            self, ("name", "ids", "keys", "source", "status"),
            ("Device", "VID:PID / interface", "Keys", "Source", "Status"), (220, 170, 60, 70, 110))
        frame.pack(fill="both", expand=True)
        btns = ttk.Frame(self)
        btns.pack(fill="x", pady=(PAD, 0))
        ttk.Button(btns, text="Learn new device...", command=self.learn).pack(side="left")
        ttk.Button(btns, text="Delete", command=self.delete).pack(side="left", padx=(PAD, 0))
        ttk.Button(btns, text="Open devices folder", command=lambda: self.service.open_folder("devices")).pack(side="left", padx=(PAD, 0))
        ttk.Button(btns, text="Refresh", command=self.refresh).pack(side="right")
        ttk.Label(self, text="Device profiles are JSON files you can share. Built-in ones ship with OpenRemap.",
                  foreground="gray45").pack(anchor="w", pady=(PAD, 0))

    @guarded
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._devs = api(self, self.service.list_devices)
        for d in self._devs:
            status = {True: "Connected", False: "Not connected", None: "Unknown"}[d["connected"]]
            ids = "%04X:%04X  if %s" % (d["vid"], d["pid"], d["interface"])
            self.tree.insert("", "end", iid=d["id"], values=(d["name"], ids, len(d["keys"]), d["source"], status),
                             tags=() if d["connected"] else ("dim",))

    def learn(self):
        saved = LearnWizard(self, self.service).show()
        if saved:
            self.app.devices_changed()

    @guarded
    def delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        dev = next(d for d in self._devs if d["id"] == sel[0])
        if dev["source"] != "user":
            messagebox.showinfo("OpenRemap", "Built-in profiles can't be deleted.", parent=self)
            return
        if messagebox.askyesno("Delete device profile", "Delete %s? Its bindings stay in your config "
                               "and come back if you learn it again with the same name." % dev["name"], parent=self):
            api(self, self.service.delete_device, dev["id"])
            self.app.devices_changed()


# ------------------------------------------------------------------- app ----

class App(tk.Tk):
    def __init__(self, service=None):
        super().__init__()
        self.service = service or RemapService()
        self.title("OpenRemap")
        self.geometry("860x560")
        self.minsize(680, 440)
        try:
            ttk.Style(self).theme_use("vista")
        except tk.TclError:
            pass

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.bindings = BindingsTab(nb, self)
        self.devices = DevicesTab(nb, self)
        nb.add(self.bindings, text="Bindings")
        nb.add(self.devices, text="Devices")

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=PAD, pady=(0, PAD))
        self.status_var = tk.StringVar(value="Changes save automatically.")
        ttk.Label(bar, textvariable=self.status_var, foreground="gray30").pack(side="left")
        self.engine_btn = ttk.Button(bar, text="Start engine", command=self.start_engine)
        self.pause_var = tk.BooleanVar()
        self.pause_chk = ttk.Checkbutton(bar, text="Paused", variable=self.pause_var, command=self.toggle_pause)
        self.pause_chk.pack(side="right")
        self.engine_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.engine_var).pack(side="right", padx=PAD)

        self.bindings.refresh_profiles()
        self.devices_changed()
        self.tick_engine()

    def notify(self, text):
        self.status_var.set(text)

    def devices_changed(self):
        self.bindings.refresh_devices()
        self.devices.refresh()

    def tick_engine(self):
        st = self.service.engine_status()
        running = st["running"]
        self.engine_var.set({True: "Engine: running", False: "Engine: not running", None: "Engine: ?"}[running])
        if running is False:
            self.engine_btn.pack(side="right", before=self.pause_chk)
        else:
            self.engine_btn.pack_forget()
        self.pause_var.set(st["paused"])
        self.after(2000, self.tick_engine)

    def start_engine(self):
        self.service.start_engine()
        self.notify("Starting the engine...")

    def toggle_pause(self):
        self.service.set_paused(self.pause_var.get())


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
