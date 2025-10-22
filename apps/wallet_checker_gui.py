import threading
import time
import random
import queue
import tkinter as tk
from tkinter import ttk


class WalletCheckerApp(tk.Tk):
    """Desktop UI that mimics the provided mini‑app screen.

    The app renders a dark theme UI with:
    - "Checked Wallets" header and a large, formatted counter
    - "Search results" list that continuously fills while scanning
    - A grid of chain icons (as text badges)
    - A large Start/Stop button and a small bottom navigation bar
    """

    def __init__(self) -> None:
        super().__init__()
        self.title("Crypto PR+ — Wallet Checker")
        self.minsize(560, 640)

        # Colors and fonts
        self._colors = {
            "bg": "#0e1320",
            "panel": "#11182a",
            "card": "#151d33",
            "text": "#e6e8f2",
            "muted": "#9aa3c7",
            "accent": "#816bff",  # purple like screenshot
            "button": "#FFFFFF",
        }
        self.configure(bg=self._colors["bg"])

        # State
        self._running_flag = threading.Event()
        self._event_queue: "queue.Queue[tuple[str, bool]]" = queue.Queue(maxsize=5000)
        self._checked_count = 0
        self._found_count = 0
        self._worker_thread: threading.Thread | None = None

        self._word_pool = _DEFAULT_WORD_POOL

        # Layout
        self._build_header()
        self._build_results_list()
        self._build_chains_grid()
        self._build_controls()
        self._build_bottom_nav()

        # Close handler
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start scanning by default to match screenshot
        self.after(50, self._drain_queue_to_ui)
        self.start()

    # ----- UI construction -----
    def _build_header(self) -> None:
        header = tk.Frame(self, bg=self._colors["bg"])  # spacing container
        header.pack(side=tk.TOP, fill=tk.X, padx=20, pady=(16, 8))

        title = tk.Label(
            header,
            text="Checked Wallets",
            bg=self._colors["bg"],
            fg=self._colors["muted"],
            font=("Segoe UI", 18, "bold"),
        )
        title.pack(anchor="w")

        self.checked_big_var = tk.StringVar(value="0")
        big = tk.Label(
            header,
            textvariable=self.checked_big_var,
            bg=self._colors["bg"],
            fg=self._colors["accent"],
            font=("Segoe UI", 48, "bold"),
        )
        big.pack(anchor="w")

        sr_title = tk.Label(
            self,
            text="Search results",
            bg=self._colors["bg"],
            fg=self._colors["text"],
            font=("Segoe UI", 20, "bold"),
        )
        sr_title.pack(side=tk.TOP, anchor="w", padx=20)

    def _build_results_list(self) -> None:
        frame = tk.Frame(self, bg=self._colors["bg"])
        frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=20, pady=(12, 6))

        self.listbox = tk.Listbox(
            frame,
            bg=self._colors["card"],
            fg=self._colors["text"],
            selectbackground="#334155",
            activestyle="none",
            highlightthickness=0,
            borderwidth=0,
            relief=tk.FLAT,
            font=("Consolas", 11),
        )
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_chains_grid(self) -> None:
        grid = tk.Frame(self, bg=self._colors["bg"])
        grid.pack(side=tk.TOP, pady=(6, 8))

        tokens: list[tuple[str, str]] = [
            ("₿", "#f7931a"),  # BTC
            ("Ξ", "#627eea"),  # ETH
            ("BNB", "#f3ba2f"),
            ("◎", "#14f195"),  # SOL
            ("AVA", "#e84142"),  # AVAX
            ("Ł", "#345c9c"),  # LTC
            ("OP", "#ff0420"),  # Optimism
            ("MATIC", "#7b3fe4"),
            ("TON", "#139bd0"),
            ("TRX", "#c51927"),
        ]

        def make_badge(parent: tk.Misc, text: str, color: str) -> tk.Label:
            return tk.Label(
                parent,
                text=text,
                bg="#0f172a",
                fg=color,
                font=("Segoe UI", 12, "bold"),
                padx=16,
                pady=10,
                relief=tk.FLAT,
            )

        cols = 5
        for idx, (glyph, color) in enumerate(tokens):
            r, c = divmod(idx, cols)
            lbl = make_badge(grid, glyph, color)
            lbl.grid(row=r, column=c, padx=10, pady=8, sticky="nsew")

    def _build_controls(self) -> None:
        ctr = tk.Frame(self, bg=self._colors["bg"])
        ctr.pack(side=tk.TOP, fill=tk.X, padx=20, pady=(8, 10))

        self.toggle_btn = tk.Button(
            ctr,
            text="Stop",
            command=self._toggle_start_stop,
            bg=self._colors["button"],
            fg="#0b0f1a",
            font=("Segoe UI", 16, "bold"),
            height=2,
        )
        self.toggle_btn.pack(fill=tk.X)

    def _build_bottom_nav(self) -> None:
        nav = tk.Frame(self, bg="#0b0f1a")
        nav.pack(side=tk.BOTTOM, fill=tk.X)
        for text in ("My profile", "Plans", "Support", "FAQ"):
            lbl = tk.Label(
                nav,
                text=text,
                bg="#0b0f1a",
                fg=self._colors["muted"],
                font=("Segoe UI", 10),
                padx=20,
                pady=10,
            )
            lbl.pack(side=tk.LEFT, expand=True)

    # ----- Actions -----
    def _toggle_start_stop(self) -> None:
        if self._running_flag.is_set():
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self._running_flag.is_set():
            return
        self._running_flag.set()
        self.toggle_btn.configure(text="Stop")
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._worker, name="wallet-checker", daemon=True)
            self._worker_thread.start()

    def stop(self) -> None:
        self._running_flag.clear()
        self.toggle_btn.configure(text="Start")

    def _on_close(self) -> None:
        self._running_flag.clear()
        self.destroy()

    # ----- Worker and UI pump -----
    def _worker(self) -> None:
        random.seed()
        while self._running_flag.is_set():
            time.sleep(0.012)
            self._checked_count += 1

            # Rare "found" message; mostly show balance 0 checks
            if self._checked_count % 37 == 0 and random.random() < 0.001:
                phrase = " ".join(random.choice(self._word_pool) for _ in range(3))
                self._event_queue.put_nowait((f"Balance > 0 | Found | {phrase}", True))
            else:
                phrase = " ".join(random.choice(self._word_pool) for _ in range(3))
                line = f"Balance 0 | Wallet check | {phrase}"
                self._event_queue.put_nowait((line, False))

            if self._checked_count % 25 == 0:
                self._event_queue.put_nowait(("__COUNTERS__", False))

    def _drain_queue_to_ui(self) -> None:
        drain_limit = 200
        processed = 0
        try:
            while processed < drain_limit:
                message, _is_found = self._event_queue.get_nowait()
                if message == "__COUNTERS__":
                    self.checked_big_var.set(f"{self._checked_count:,}")
                else:
                    self._append_line(message)
                processed += 1
        except queue.Empty:
            pass

        # Keep the big counter fresh
        self.checked_big_var.set(f"{self._checked_count:,}")

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
    # Harmless pool of common words (not BIP‑39)
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
