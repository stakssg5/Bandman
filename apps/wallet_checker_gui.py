import threading
import time
import random
import queue
import tkinter as tk
from tkinter import ttk


class WalletCheckerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Software")
        self.minsize(520, 460)

        # State
        self._running_flag = threading.Event()
        self._event_queue: "queue.Queue[str]" = queue.Queue(maxsize=5000)
        self._checked_count = 0
        self._found_count = 0
        self._worker_thread: threading.Thread | None = None

        # Top bar
        top_frame = ttk.Frame(self)
        top_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(10, 6))

        self.checked_var = tk.StringVar(value="Checked: 0")
        checked_label = ttk.Label(top_frame, textvariable=self.checked_var, font=("Segoe UI", 11, "bold"))
        checked_label.pack(side=tk.LEFT)

        # Spacer
        ttk.Label(top_frame, text=" ").pack(side=tk.LEFT, expand=True)

        # Simple Bitcoin symbol on the right
        btc_label = ttk.Label(top_frame, text="₿", foreground="#f7931a", font=("Segoe UI", 16, "bold"))
        btc_label.pack(side=tk.RIGHT)

        # Middle list (black background like a console)
        mid_frame = ttk.Frame(self)
        mid_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10)

        self.listbox = tk.Listbox(
            mid_frame,
            bg="#111111",
            fg="#eaeaea",
            selectbackground="#444444",
            activestyle="none",
            highlightthickness=0,
            borderwidth=1,
            relief=tk.SOLID,
            font=("Consolas", 10),
        )
        scrollbar = ttk.Scrollbar(mid_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)

        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Bottom area with Found label and buttons
        bottom_frame = ttk.Frame(self)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(6, 10))

        self.found_var = tk.StringVar(value="Found: 0")
        found_label = ttk.Label(bottom_frame, textvariable=self.found_var, font=("Segoe UI", 11, "bold"))
        found_label.pack(side=tk.LEFT)

        # Buttons container
        btns = ttk.Frame(bottom_frame)
        btns.pack(side=tk.RIGHT)

        self.start_btn = tk.Button(btns, text="START", width=12, bg="#1ea34a", fg="white", activebackground="#19833c", command=self.start)
        self.stop_btn = tk.Button(btns, text="STOP", width=12, bg="#c8342b", fg="white", activebackground="#9f2a22", command=self.stop, state=tk.DISABLED)
        self.start_btn.grid(row=0, column=0, padx=(0, 8))
        self.stop_btn.grid(row=0, column=1)

        # Kick off the UI queue pump
        self.after(50, self._drain_queue_to_ui)

        # Words pool used to generate dummy lines
        self._word_pool = _DEFAULT_WORD_POOL

        # Close handler
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # UI Actions
    def start(self) -> None:
        if self._running_flag.is_set():
            return
        self._running_flag.set()
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._worker, name="wallet-checker", daemon=True)
            self._worker_thread.start()

    def stop(self) -> None:
        self._running_flag.clear()
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        self._running_flag.clear()
        self.destroy()

    # Background worker
    def _worker(self) -> None:
        random.seed()
        while self._running_flag.is_set():
            # Simulate work rate
            time.sleep(0.01)

            self._checked_count += 1
            if self._checked_count % 37 == 0 and random.random() < 0.001:
                self._found_count += 1
                self._event_queue.put_nowait((f"FOUND candidate #{self._found_count}", True))
            else:
                phrase = " ".join(random.choice(self._word_pool) for _ in range(12))
                self._event_queue.put_nowait((f"Wallet check: {phrase}", False))

            # Update header every ~50 iterations to reduce UI churn
            if self._checked_count % 50 == 0:
                self._event_queue.put_nowait(("__COUNTERS__", False))

    # UI pump
    def _drain_queue_to_ui(self) -> None:
        drain_limit = 200
        processed = 0
        try:
            while processed < drain_limit:
                item = self._event_queue.get_nowait()
                message, is_found = item
                if message == "__COUNTERS__":
                    self.checked_var.set(f"Checked: {self._checked_count}")
                    self.found_var.set(f"Found: {self._found_count}")
                else:
                    if is_found:
                        self.found_var.set(f"Found: {self._found_count}")
                    self._append_line(message)
                processed += 1
        except queue.Empty:
            pass

        # Always keep the counters fresh even if queue was empty
        self.checked_var.set(f"Checked: {self._checked_count}")
        self.found_var.set(f"Found: {self._found_count}")

        # schedule next pump
        self.after(50, self._drain_queue_to_ui)

    def _append_line(self, text: str) -> None:
        # Cap list size to keep memory bounded
        max_items = 1000
        if self.listbox.size() > max_items:
            self.listbox.delete(0, self.listbox.size() - max_items)
        self.listbox.insert(tk.END, text)
        self.listbox.yview_moveto(1.0)


_DEFAULT_WORD_POOL = (
    "private gun alien elite ten behave inject rotate say vague title prosper"
).split() + [
    # A compact, harmless pool of common words (not BIP-39)
    "empower", "profit", "body", "fog", "buffalo", "cabbage", "tube", "course", "host", "initial",
    "spider", "glimpse", "dog", "category", "pump", "cinnamon", "pride", "inspire", "day", "carnivore",
    "boost", "waste", "fragile", "tortoise", "warm", "drive", "dead", "palm", "stamina", "fragile",
    "witness", "kite", "kind", "relax", "brick", "hour", "lab", "soul", "solution", "thirty",
    "quit", "chisel", "unable", "throne", "veteran", "jaguar", "sight", "quarter", "powder", "aerobic",
    "despair", "stumble", "curtain", "prayer", "velvet", "harbor", "glory", "stable", "oxygen", "explain",
    "bubble", "dawn", "zebra", "ramp", "noble", "silver", "cargo", "couch", "ember", "forest",
    "magnet", "gargle", "marble", "pencil", "radar", "salad", "talent", "umpire", "vacuum", "wagon",
    "yacht", "zero", "acorn", "bacon", "cannon", "daisy", "engine", "fabric", "galaxy", "hammer",
    "icicle", "jungle", "kitten", "ladder", "mantle", "nectar", "oyster", "pepper", "quartz", "rocket",
    "sandal", "tartan", "utopia", "violet", "willow", "xenon", "yellow", "zephyr",
]


def main() -> None:
    app = WalletCheckerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
