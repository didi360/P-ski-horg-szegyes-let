import datetime
import locale
import os
import shutil
import sqlite3
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

# --- PIL (Pillow) IMPORTÁLÁS A KÉPKEZELÉSHEZ ---
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# --- REPORTLAB IMPORTÁLÁSOK ---
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

try:
    from xhtml2pdf import pisa

    XHTML2PDF_AVAILABLE = True
except ImportError:
    XHTML2PDF_AVAILABLE = False


# --- ADATBÁZIS INICIALIZÁLÁSA ---
def init_db(db_name="horgaszat.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS horgaszok (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nev TEXT UNIQUE NOT NULL
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS fogasok (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            horgasz_id INTEGER,
            datum TEXT NOT NULL,
            hal_fajta TEXT NOT NULL,
            kg REAL NOT NULL,
            FOREIGN KEY (horgasz_id) REFERENCES horgaszok (id) ON DELETE CASCADE
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS beallitasok (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            q1_start TEXT DEFAULT '01-01', q1_end TEXT DEFAULT '03-31', q1_limit INTEGER DEFAULT 15,
            q2_start TEXT DEFAULT '04-01', q2_end TEXT DEFAULT '06-30', q2_limit INTEGER DEFAULT 15,
            q3_start TEXT DEFAULT '07-01', q3_end TEXT DEFAULT '09-30', q3_limit INTEGER DEFAULT 15,
            q4_start TEXT DEFAULT '10-01', q4_end TEXT DEFAULT '12-31', q4_limit INTEGER DEFAULT 15,
            keszeg_limit REAL DEFAULT 10.0
        )
    """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS halfajok (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nev TEXT UNIQUE NOT NULL,
            eves_kvota INTEGER DEFAULT 0,
            feherhal_kvota INTEGER DEFAULT 0
        )
    """
    )

    cursor.execute("SELECT COUNT(*) FROM halfajok")
    if cursor.fetchone()[0] == 0:
        alap_halak = [
            ("Ponty", 1, 0),
            ("Csuka", 1, 0),
            ("Amur", 1, 0),
            ("Harcsa", 1, 0),
            ("Süllő", 1, 0),
            ("Balin", 1, 0),
            ("Kárász", 0, 1),
            ("Keszeg", 0, 1)
        ]
        for h_nev, ek, fk in alap_halak:
            try:
                cursor.execute("INSERT INTO halfajok (nev, eves_kvota, feherhal_kvota) VALUES (?, ?, ?)", (h_nev, ek, fk))
            except sqlite3.IntegrityError:
                pass

    try:
        cursor.execute("ALTER TABLE beallitasok ADD COLUMN keszeg_limit REAL DEFAULT 10.0")
    except sqlite3.OperationalError:
        pass

    cursor.execute("SELECT COUNT(*) FROM beallitasok")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO beallitasok (id) VALUES (1)")

    cursor.execute("SELECT COUNT(*) FROM horgaszok")
    if cursor.fetchone()[0] == 0:
        minta_nevek = [
            "Kiss Pista",
            "Nagy János",
            "Szabó Anna",
            "Tóth Gábor",
            "Varga Éva",
            "Horváth Péter",
        ]
        for nev in minta_nevek:
            cursor.execute("INSERT INTO horgaszok (nev) VALUES (?)", (nev,))

    conn.commit()
    conn.close()


def get_settings(db_name="horgaszat.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM beallitasok WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    if row:
        return {
            "Q1": {"start": row[1], "end": row[2], "limit": row[3]},
            "Q2": {"start": row[4], "end": row[5], "limit": row[6]},
            "Q3": {"start": row[7], "end": row[8], "limit": row[9]},
            "Q4": {"start": row[10], "end": row[11], "limit": row[12]},
            "keszeg_limit": row[13] if len(row) > 13 and row[13] is not None else 10.0
        }
    return {}


def get_halfaj_tipusok(db_name="horgaszat.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("SELECT nev, eves_kvota, feherhal_kvota FROM halfajok")
    rows = cursor.fetchall()
    conn.close()
    
    eves_list = []
    feherhal_list = []
    all_list = []
    
    for nev, ek, fk in rows:
        all_list.append(nev)
        if ek == 1:
            eves_list.append(nev)
        elif fk == 1:
            feherhal_list.append(nev)
            
    return all_list, eves_list, feherhal_list


def check_date_in_quarter(datum_obj, start_str, end_str):
    year = datum_obj.year
    try:
        s_m, s_d = map(int, start_str.split("-"))
        e_m, e_d = map(int, end_str.split("-"))
        start_date = datetime.date(year, s_m, s_d)
        end_date = datetime.date(year, e_m, e_d)

        if start_date <= end_date:
            return start_date <= datum_obj <= end_date
        else:
            end_date_next = datetime.date(year + 1, e_m, e_d)
            start_date_prev = datetime.date(year - 1, s_m, s_d)
            return (start_date <= datum_obj <= end_date_next) or (
                start_date_prev <= datum_obj <= end_date
            )
    except Exception:
        return False


def get_quarter_for_date(datum_obj, db_name="horgaszat.db"):
    settings = get_settings(db_name)
    for q_key in ["Q1", "Q2", "Q3", "Q4"]:
        q_info = settings[q_key]
        if check_date_in_quarter(datum_obj, q_info["start"], q_info["end"]):
            return q_key, q_info["limit"], q_info["start"], q_info["end"]
    return None, None, None, None


def is_horgasz_exceeded(horgasz_id, db_name="horgaszat.db"):
    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT datum, hal_fajta, kg FROM fogasok WHERE horgasz_id = ?",
        (horgasz_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    settings = get_settings(db_name)
    max_keszeg = settings.get("keszeg_limit", 10.0)
    current_year = datetime.datetime.now().year

    _, eves_halak, feherhalak = get_halfaj_tipusok(db_name)

    q_counts = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    feherhal_kg = 0.0

    for r_datum, r_hal, r_kg in rows:
        try:
            r_date = datetime.datetime.strptime(r_datum, "%Y-%m-%d").date()
        except ValueError:
            continue

        if r_hal in feherhalak:
            if r_date.year == current_year:
                feherhal_kg += r_kg
                if feherhal_kg > max_keszeg:
                    return True
        elif r_hal in eves_halak:
            q_name, q_lim, q_start, q_end = get_quarter_for_date(r_date, db_name)
            if q_name and q_lim is not None:
                q_counts[q_name] += 1
                if q_counts[q_name] > q_lim:
                    return True

    return False


# --- FŐ ALKALMAZÁS ---
class HorgaszApp:

    def __init__(self, root, db_name="horgaszat.db", is_archived=False):
        self.root = root
        self.db_name = db_name
        self.is_archived = is_archived
        
        if not self.is_archived:
            self.root.title("Püski Horgász Egyesület")
            self.root.geometry("1150x700")
            init_db(self.db_name)
        else:
            self.root.title(f"Archívum - {db_name}")
            self.root.geometry("1150x700")

        self.root.configure(bg="#F1F5F9")
        self.setup_styles()
        
        if not self.is_archived:
            self.show_splash_screen()
        else:
            self.init_main_app()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=4)

        style.configure(
            "RedHeader.Treeview",
            rowheight=28,
            gridcolor="#E2E8F0",
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            font=("Segoe UI", 9),
        )
        style.configure(
            "RedHeader.Treeview.Heading",
            font=("Segoe UI", 8, "bold"),
            background="#FEE2E2",
            foreground="#991B1B",
            relief="flat",
        )

        style.configure("Red.TNotebook", background="#F1F5F9")
        style.configure(
            "Red.TNotebook.Tab",
            font=("Segoe UI", 9, "bold"),
            padding=[12, 6],
            background="#FEE2E2",
            foreground="#991B1B",
        )
        style.map(
            "Red.TNotebook.Tab",
            background=[("selected", "#DC2626")],
            foreground=[("selected", "#FFFFFF")],
        )

    def get_db_connection(self):
        conn = sqlite3.connect(self.db_name)
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def show_splash_screen(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        splash_frame = tk.Frame(self.root, bg="#111827")
        splash_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(splash_frame, bg="#111827", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        image_path = "1788795161591.png"

        def render_splash(event=None):
            canvas.delete("all")
            w = max(self.root.winfo_width(), 1150)
            h = max(self.root.winfo_height(), 700)

            if PIL_AVAILABLE and os.path.exists(image_path):
                try:
                    pil_img = Image.open(image_path)
                    pil_img = pil_img.resize((w, h), Image.Resampling.LANCZOS)
                    self.bg_photo = ImageTk.PhotoImage(pil_img)
                    canvas.create_image(0, 0, image=self.bg_photo, anchor="nw")
                except Exception:
                    canvas.create_rectangle(0, 0, w, h, fill="#1e293b", outline="")
            else:
                canvas.create_rectangle(0, 0, w, h, fill="#1e293b", outline="")

            def on_click(e):
                canvas.unbind("<Configure>")
                canvas.unbind("<Button-1>")
                self.init_main_app()

            canvas.bind("<Button-1>", on_click)

        canvas.bind("<Configure>", render_splash)

    def init_main_app(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        self.main_container = tk.Frame(self.root, bg="#F1F5F9")
        self.main_container.pack(fill=tk.BOTH, expand=True)

        self.sidebar = tk.Frame(self.main_container, bg="#DC2626", width=220)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        title_frame = tk.Frame(self.sidebar, bg="#DC2626")
        title_frame.pack(fill=tk.X, pady=(20, 30), padx=15)

        title_text = "🎣 Horgászok" if not self.is_archived else "📂 Archív Mód"
        tk.Label(
            title_frame,
            text=title_text,
            font=("Segoe UI", 14, "bold"),
            bg="#DC2626",
            fg="white",
            anchor="w",
        ).pack(fill=tk.X)

        self.menu_buttons = {}
        
        if not self.is_archived:
            menu_items = [
                ("emberek", "👥 Emberek", self.show_emberek_page),
                ("osszesites", "📊 Összegző", self.show_osszesites_page),
                ("ranglista", "🏆 Ranglista", self.show_ranglista_page),
                ("osszes_halfaj", "🐟 Összes halfaj", self.show_osszes_halfaj_page),
                ("halfaj_hozzaadas", "➕ Halfaj hozzáadása", self.show_halfaj_hozzaadas_page),
                ("halfaj_torles", "🗑️ Halfaj törlése", self.show_halfaj_torles_page),
                ("negyedevek", "📅 Negyedévek beállítása", self.show_negyedevek_page),
                ("eloz_evek", "📁 Előző évek", self.show_elozetes_evek_page),
                ("mentes", "💾 Új év kezdése", self.reset_new_year),
            ]
        else:
            menu_items = [
                ("emberek", "👥 Emberek (Napló)", self.show_emberek_page),
                ("osszesites", "📊 Összegző", self.show_osszesites_page),
                ("ranglista", "🏆 Ranglista", self.show_ranglista_page),
                ("osszes_halfaj", "🐟 Összes halfaj", self.show_osszes_halfaj_page),
                ("vissza", "↩️ Vissza a főbe", lambda: self.root.destroy()),
            ]

        for key, text, cmd in menu_items:
            btn = tk.Button(
                self.sidebar,
                text=text,
                font=("Segoe UI", 10, "bold"),
                bg="#DC2626",
                fg="#FEE2E2",
                activebackground="#B91C1C",
                activeforeground="white",
                bd=0,
                padx=20,
                pady=10,
                anchor="w",
                cursor="hand2",
                command=cmd,
            )
            btn.pack(fill=tk.X)
            self.menu_buttons[key] = btn

        self.content_area = tk.Frame(self.main_container, bg="#F1F5F9")
        self.content_area.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.top_red_bar = tk.Frame(self.content_area, bg="#DC2626", height=50)
        self.page_frame = tk.Frame(self.content_area, bg="#F1F5F9")
        self.page_frame.pack(fill=tk.BOTH, expand=True)

        self.selected_card_nev = None
        self.show_emberek_page()

    def clear_page(self):
        self.top_red_bar.pack_forget()
        for widget in self.top_red_bar.winfo_children():
            widget.destroy()
        for widget in self.page_frame.winfo_children():
            widget.destroy()

    def setActiveMenu(self, active_key):
        for key, btn in self.menu_buttons.items():
            if key == active_key:
                btn.config(bg="#B91C1C", fg="white")
            else:
                btn.config(bg="#DC2626", fg="#FEE2E2")

    def show_osszes_halfaj_page(self):
        self.setActiveMenu("osszes_halfaj")
        self.clear_page()

        header_bar = tk.Frame(self.page_frame, bg="#DC2626", height=45)
        header_bar.pack(fill=tk.X)

        tk.Label(
            header_bar,
            text="🐟 Összes halfaj és rekordok",
            font=("Segoe UI", 12, "bold"),
            bg="#DC2626",
            fg="white",
        ).pack(side=tk.LEFT, padx=15, pady=10)

        content_bg = tk.Frame(self.page_frame, bg="#F1F5F9", padx=20, pady=20)
        content_bg.pack(fill=tk.BOTH, expand=True)

        tree_frame = tk.Frame(content_bg, bg="white", bd=1, relief="solid")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)

        tree = ttk.Treeview(
            tree_frame,
            columns=("faj", "suly", "horgasz", "datum"),
            show="headings",
            style="RedHeader.Treeview",
            yscrollcommand=scroll_y.set,
        )

        scroll_y.config(command=tree.yview)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True)

        tree.heading("faj", text="HALFAJ")
        tree.heading("suly", text="LEGNAGYOBB SÚLY (KG)")
        tree.heading("horgasz", text="FOGÓ NEVE")
        tree.heading("datum", text="DÁTUM")

        tree.column("faj", width=200, anchor="w")
        tree.column("suly", width=180, anchor="center")
        tree.column("horgasz", width=250, anchor="w")
        tree.column("datum", width=150, anchor="center")

        tree.tag_configure("even_row", background="#FFFFFF")
        tree.tag_configure("odd_row", background="#FAFAFA")

        all_halak, _, _ = get_halfaj_tipusok(self.db_name)
        
        conn = self.get_db_connection()
        cursor = conn.cursor()

        for idx, hal in enumerate(sorted(all_halak)):
            cursor.execute("""
                SELECT f.kg, h.nev, f.datum 
                FROM fogasok f 
                JOIN horgaszok h ON f.horgasz_id = h.id 
                WHERE f.hal_fajta = ? 
                ORDER BY f.kg DESC, f.datum ASC 
                LIMIT 1
            """, (hal,))
            res = cursor.fetchone()

            if res:
                max_kg, horgasz_neve, datum = res
                suly_str = f"{max_kg:.1f} kg".replace(".", ",")
                datum_str = datum
            else:
                suly_str = "Még nincs fogás"
                horgasz_neve = "-"
                datum_str = "-"

            tag = "even_row" if idx % 2 == 0 else "odd_row"
            tree.insert("", tk.END, values=(f"  {hal}", suly_str, f"  {horgasz_neve}", datum_str), tags=(tag,))

        conn.close()

    def show_halfaj_hozzaadas_page(self):
        if self.is_archived:
            return
        self.setActiveMenu("halfaj_hozzaadas")
        self.clear_page()

        header_bar = tk.Frame(self.page_frame, bg="#DC2626", height=45)
        header_bar.pack(fill=tk.X)

        tk.Label(
            header_bar,
            text="➕ Halfaj hozzáadása",
            font=("Segoe UI", 12, "bold"),
            bg="#DC2626",
            fg="white",
        ).pack(side=tk.LEFT, padx=15, pady=10)

        canvas = tk.Canvas(self.page_frame, bg="#FCE7E7", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        def draw_bg(event=None):
            canvas.delete("bg")
            w = max(self.page_frame.winfo_width(), 900)
            h = max(self.page_frame.winfo_height(), 600)
            canvas.create_rectangle(0, 0, w, h, fill="#FDF2F2", tags="bg")
            canvas.tag_raise("content")

        canvas.bind("<Configure>", draw_bg)

        container = tk.Frame(canvas, bg="#FDF2F2")
        window_id = canvas.create_window(450, 250, window=container, anchor="center", tags="content")

        def center_form(event=None):
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            canvas.coords(window_id, w / 2, h / 2)

        canvas.bind("<Configure>", lambda e: [draw_bg(e), center_form(e)])

        card1 = tk.Frame(container, bg="#FFFFFF", bd=1, relief="solid", padx=25, pady=15)
        card1.pack(fill=tk.X, pady=10)
        tk.Label(card1, text="🐟 Halfaj neve", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#991B1B", anchor="w").pack(fill=tk.X)
        hal_nev_entry = tk.Entry(card1, font=("Segoe UI", 10), bd=1, relief="solid")
        hal_nev_entry.pack(fill=tk.X, pady=(5, 5), ipady=4)
        hal_nev_entry.insert(0, "Írd be a halfaj nevét...")
        def on_f_in(e):
            if hal_nev_entry.get() == "Írd be a halfaj nevét...":
                hal_nev_entry.delete(0, tk.END)
                hal_nev_entry.config(fg="#000000")
        def on_f_out(e):
            if not hal_nev_entry.get():
                hal_nev_entry.insert(0, "Írd be a halfaj nevét...")
                hal_nev_entry.config(fg="#94A3B8")
        hal_nev_entry.config(fg="#94A3B8")
        hal_nev_entry.bind("<FocusIn>", on_f_in)
        hal_nev_entry.bind("<FocusOut>", on_f_out)

        var_eves = tk.IntVar(value=0)
        var_feherhal = tk.IntVar(value=0)

        def toggle_eves():
            if var_eves.get() == 1:
                var_feherhal.set(0)

        def toggle_feherhal():
            if var_feherhal.get() == 1:
                var_eves.set(0)

        card2 = tk.Frame(container, bg="#FFFFFF", bd=1, relief="solid", padx=25, pady=15)
        card2.pack(fill=tk.X, pady=10)
        
        row2_left = tk.Frame(card2, bg="#FFFFFF")
        row2_left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(row2_left, text="🐟 beletartozik az éves kvótába", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#991B1B", anchor="w").pack(fill=tk.X)

        row2_right = tk.Frame(card2, bg="#FFFFFF")
        row2_right.pack(side=tk.RIGHT)

        chk_eves_igen = tk.Checkbutton(row2_right, text="Igen", variable=var_eves, command=toggle_eves, font=("Segoe UI", 9, "bold"), bg="#FFFFFF", selectcolor="#FEE2E2")
        chk_eves_igen.pack(side=tk.LEFT)

        card3 = tk.Frame(container, bg="#FFFFFF", bd=1, relief="solid", padx=25, pady=15)
        card3.pack(fill=tk.X, pady=10)

        row3_left = tk.Frame(card3, bg="#FFFFFF")
        row3_left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(row3_left, text="🐟 beletartozik az éves fehérhal kvótába", font=("Segoe UI", 9, "bold"), bg="#FFFFFF", fg="#991B1B", anchor="w").pack(fill=tk.X)

        row3_right = tk.Frame(card3, bg="#FFFFFF")
        row3_right.pack(side=tk.RIGHT)

        chk_feher_igen = tk.Checkbutton(row3_right, text="Igen", variable=var_feherhal, command=toggle_feherhal, font=("Segoe UI", 9, "bold"), bg="#FFFFFF", selectcolor="#FEE2E2")
        chk_feher_igen.pack(side=tk.LEFT)

        def save_halfaj():
            nev = hal_nev_entry.get().strip()
            if not nev or nev == "Írd be a halfaj nevét...":
                messagebox.showerror("Hiba", "Add meg a halfaj nevét!")
                return
            
            ek = var_eves.get()
            fk = var_feherhal.get()

            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO halfajok (nev, eves_kvota, feherhal_kvota) VALUES (?, ?, ?)", (nev, ek, fk))
                conn.commit()
                messagebox.showinfo("Siker", f"'{nev}' nevű halfaj sikeresen hozzáadva!")
                hal_nev_entry.delete(0, tk.END)
                var_eves.set(0)
                var_feherhal.set(0)
            except sqlite3.IntegrityError:
                messagebox.showerror("Hiba", "Ilyen nevű halfaj már létezik az adatbázisban!")
            finally:
                conn.close()

        btn_mentes = tk.Button(
            container,
            text="Mentés 🐟",
            font=("Segoe UI", 11, "bold"),
            bg="#991B1B",
            fg="#FFFFFF",
            activebackground="#7F1D1D",
            activeforeground="#FFFFFF",
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
            command=save_halfaj
        )
        btn_mentes.pack(fill=tk.X, pady=15)

    def show_halfaj_torles_page(self):
        if self.is_archived:
            return
        self.setActiveMenu("halfaj_torles")
        self.clear_page()

        header_bar = tk.Frame(self.page_frame, bg="#DC2626", height=45)
        header_bar.pack(fill=tk.X)

        tk.Label(
            header_bar,
            text="🗑️ Halfaj törlése",
            font=("Segoe UI", 12, "bold"),
            bg="#DC2626",
            fg="white",
        ).pack(side=tk.LEFT, padx=15, pady=10)

        canvas = tk.Canvas(self.page_frame, bg="#FDF2F2", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        def draw_bg(event=None):
            canvas.delete("bg")
            w = max(self.page_frame.winfo_width(), 900)
            h = max(self.page_frame.winfo_height(), 600)
            canvas.create_rectangle(0, 0, w, h, fill="#FDF2F2", tags="bg")
            canvas.tag_raise("content")

        canvas.bind("<Configure>", draw_bg)

        container = tk.Frame(canvas, bg="#FDF2F2")
        window_id = canvas.create_window(450, 250, window=container, anchor="center", tags="content")

        def center_form(event=None):
            w = canvas.winfo_width()
            h = canvas.winfo_height()
            canvas.coords(window_id, w / 2, h / 2)

        canvas.bind("<Configure>", lambda e: [draw_bg(e), center_form(e)])

        card = tk.Frame(container, bg="#FFFFFF", bd=1, relief="solid", padx=30, pady=25)
        card.pack(fill=tk.X, pady=10)

        tk.Label(card, text="🗑️ Válassz ki egy törlendő halfajt:", font=("Segoe UI", 10, "bold"), bg="#FFFFFF", fg="#991B1B", anchor="w").pack(fill=tk.X, pady=(0, 8))

        all_halak, _, _ = get_halfaj_tipusok(self.db_name)
        hal_cb = ttk.Combobox(card, values=all_halak, state="readonly", font=("Segoe UI", 10))
        hal_cb.pack(fill=tk.X, pady=(0, 20), ipady=4)
        if all_halak:
            hal_cb.set(all_halak[0])

        def execute_delete_halfaj():
            valasztott_hal = hal_cb.get().strip()
            if not valasztott_hal:
                messagebox.showerror("Hiba", "Nincs kiválasztva halfaj!")
                return

            alap_fajok = ["Ponty", "Csuka", "Amur", "Harcsa", "Süllő", "Balin", "Kárász", "Keszeg"]
            if valasztott_hal in alap_fajok:
                messagebox.showerror("Hiba", f"A(z) '{valasztott_hal}' alapfaj, így azt nem lehet törölni!")
                return

            ans1 = messagebox.askyesno(
                "⚠️ 1. Mehet a törlés?",
                f"Biztosan ki akarod törölni a(z) '{valasztott_hal}' halfajt?",
                parent=self.root
            )
            if not ans1:
                return

            ans2 = messagebox.askyesno(
                "🚨 2. Komoly figyelmeztetés!",
                f"A(z) '{valasztott_hal}' véglegesen eltűnik a rendszerből és a választási lehetőségek közül!\n\nBiztosan folytatod?",
                parent=self.root
            )
            if not ans2:
                return

            conf_str = simpledialog.askstring(
                "🛑 3. Utolsó megerősítés",
                f"A törlés véglegesítéséhez írd be pontosan: TÖRLÉS",
                parent=self.root
            )

            if conf_str and conf_str.strip().upper() == "TÖRLÉS":
                conn = self.get_db_connection()
                cursor = conn.cursor()
                try:
                    cursor.execute("DELETE FROM halfajok WHERE nev = ?", (valasztott_hal,))
                    conn.commit()
                    messagebox.showinfo("Siker", f"A(z) '{valasztott_hal}' halfaj sikeresen törölve lett!")
                    friss_halak, _, _ = get_halfaj_tipusok(self.db_name)
                    hal_cb["values"] = friss_halak
                    if friss_halak:
                        hal_cb.set(friss_halak[0])
                    else:
                        hal_cb.set("")
                except Exception as e:
                    messagebox.showerror("Hiba", f"Hiba történt a törlés során: {e}")
                finally:
                    conn.close()
            else:
                messagebox.showwarning("Megszakítva", "A megerősítő szó nem egyezett, a törlés megszakadt.")

        btn_torles = tk.Button(
            card,
            text="Halfaj végleges törlése 🗑️",
            font=("Segoe UI", 10, "bold"),
            bg="#991B1B",
            fg="#FFFFFF",
            activebackground="#7F1D1D",
            activeforeground="#FFFFFF",
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
            command=execute_delete_halfaj
        )
        btn_torles.pack(fill=tk.X)

    def show_emberek_page(self):
        menu_name = "emberek" if not self.is_archived else "emberek"
        self.setActiveMenu(menu_name)
        self.clear_page()

        self.top_red_bar.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(
            self.top_red_bar,
            text="🎣 Horgászok" + (" (Archív)" if self.is_archived else ""),
            font=("Segoe UI", 12, "bold"),
            bg="#DC2626",
            fg="white",
        )
        title_lbl.pack(side=tk.LEFT, padx=(15, 20), pady=10)

        search_frame = tk.Frame(self.top_red_bar, bg="white", bd=0)
        search_frame.pack(side=tk.LEFT, padx=10, pady=8)

        search_icon = tk.Label(
            search_frame, text="🔍", bg="white", fg="#94A3B8", font=("Segoe UI", 9)
        )
        search_icon.pack(side=tk.LEFT, padx=(8, 2))

        self.search_entry = tk.Entry(
            search_frame,
            font=("Segoe UI", 9),
            bd=0,
            bg="white",
            fg="#334155",
            width=28,
        )
        self.search_entry.pack(side=tk.LEFT, ipady=4, padx=(0, 8))
        self.search_entry.insert(0, "Keresés név szerint...")

        def on_focus_in(e):
            if self.search_entry.get() == "Keresés név szerint...":
                self.search_entry.delete(0, tk.END)
                self.search_entry.config(fg="#0F172A")

        def on_focus_out(e):
            if not self.search_entry.get():
                self.search_entry.insert(0, "Keresés név szerint...")
                self.search_entry.config(fg="#94A3B8")

        self.search_entry.bind("<FocusIn>", on_focus_in)
        self.search_entry.bind("<FocusOut>", on_focus_out)
        self.search_entry.bind("<KeyRelease>", lambda e: self.load_emberek_cards())

        if not self.is_archived:
            btn_del = tk.Button(
                self.top_red_bar,
                text="➖ Ember eltávolítás",
                font=("Segoe UI", 9, "bold"),
                bg="white",
                fg="#DC2626",
                activebackground="#FEE2E2",
                bd=0,
                padx=10,
                pady=4,
                cursor="hand2",
                command=self.delete_horgasz_prompt,
            )
            btn_del.pack(side=tk.RIGHT, padx=(5, 15), pady=8)

            btn_add = tk.Button(
                self.top_red_bar,
                text="➕ Ember felvétele",
                font=("Segoe UI", 9, "bold"),
                bg="white",
                fg="#059669",
                activebackground="#D1FAE5",
                bd=0,
                padx=10,
                pady=4,
                cursor="hand2",
                command=self.add_horgasz_prompt,
            )
            btn_add.pack(side=tk.RIGHT, padx=5, pady=8)

        canvas = tk.Canvas(self.page_frame, bg="#F1F5F9", highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            self.page_frame, orient="vertical", command=canvas.yview
        )
        self.cards_scroll_frame = tk.Frame(canvas, bg="#F1F5F9")

        self.cards_scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.cards_scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=10)

        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        self.load_emberek_cards()

    def get_monogram(self, nev):
        parts = nev.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[1][0]).upper()
        elif parts:
            return parts[0][:2].upper()
        return "??"

    def load_emberek_cards(self):
        for widget in self.cards_scroll_frame.winfo_children():
            widget.destroy()

        search_query = self.search_entry.get().strip().lower()
        if search_query == "keresés név szerint...":
            search_query = ""

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, nev FROM horgaszok ORDER BY nev ASC")
        rows = cursor.fetchall()

        _, _, feherhalak = get_halfaj_tipusok(self.db_name)

        grouped = {}
        for h_id, h_nev in rows:
            if search_query and search_query not in h_nev.lower():
                continue

            first_char = h_nev[0].upper() if h_nev else "#"

            placeholders = ','.join(['?'] * len(feherhalak)) if feherhalak else "'__DUMMY__'"
            if feherhalak:
                cursor.execute(f"""
                    SELECT COUNT(*), SUM(kg) FROM fogasok 
                    WHERE horgasz_id = ? AND hal_fajta NOT IN ({placeholders})
                """, [h_id] + feherhalak)
            else:
                cursor.execute("""
                    SELECT COUNT(*), SUM(kg) FROM fogasok 
                    WHERE horgasz_id = ?
                """, (h_id,))
            c, k = cursor.fetchone()

            if feherhalak:
                cursor.execute(f"""
                    SELECT SUM(kg) FROM fogasok 
                    WHERE horgasz_id = ? AND hal_fajta IN ({placeholders})
                """, [h_id] + feherhalak)
            else:
                kk_weight = 0.0
                
            kk_res = cursor.fetchone()[0] if feherhalak else 0.0
            kk_weight = kk_res if kk_res else 0.0

            exceeded = is_horgasz_exceeded(h_id, self.db_name)

            grouped.setdefault(first_char, []).append(
                (h_id, h_nev, c if c else 0, k if k else 0.0, kk_weight, exceeded)
            )

        conn.close()

        if not grouped:
            empty_lbl = tk.Label(
                self.cards_scroll_frame,
                text="Nincs találat.",
                font=("Segoe UI", 11),
                bg="#F1F5F9",
                fg="#64748B",
            )
            empty_lbl.pack(pady=30)
            return

        for group_char in sorted(grouped.keys()):
            group_lbl = tk.Label(
                self.cards_scroll_frame,
                text=group_char,
                font=("Segoe UI", 11, "bold"),
                bg="#F1F5F9",
                fg="#475569",
            )
            group_lbl.pack(anchor="w", padx=10, pady=(15, 5))

            for (
                h_id,
                h_nev,
                count_val,
                weight_val,
                kk_weight,
                exceeded,
            ) in grouped[group_char]:
                card_bg = "#FEF2F2" if exceeded else "white"
                card_border = "#FCA5A5" if exceeded else "white"

                card = tk.Frame(
                    self.cards_scroll_frame,
                    bg=card_bg,
                    highlightbackground=card_border,
                    highlightthickness=1 if exceeded else 0,
                    bd=0,
                    cursor="hand2",
                    padx=20,
                    pady=18,
                )
                card.pack(fill=tk.X, expand=True, padx=10, pady=8)

                mono_bg = "#FCA5A5" if exceeded else "#FEE2E2"
                mono_fg = "#7F1D1D" if exceeded else "#DC2626"

                mono_frame = tk.Frame(card, bg=mono_bg, width=48, height=48)
                mono_frame.pack_propagate(False)
                mono_frame.pack(side=tk.LEFT, padx=(0, 18))

                mono_lbl = tk.Label(
                    mono_frame,
                    text=self.get_monogram(h_nev),
                    font=("Segoe UI", 12, "bold"),
                    bg=mono_bg,
                    fg=mono_fg,
                )
                mono_lbl.pack(expand=True)

                info_frame = tk.Frame(card, bg=card_bg)
                info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

                name_row = tk.Frame(info_frame, bg=card_bg)
                name_row.pack(fill=tk.X)

                name_lbl = tk.Label(
                    name_row,
                    text=h_nev,
                    font=("Segoe UI", 12, "bold"),
                    bg=card_bg,
                    fg="#0F172A",
                    anchor="w",
                )
                name_lbl.pack(side=tk.LEFT)

                if exceeded:
                    warn_lbl = tk.Label(
                        name_row,
                        text=" ⚠️ LIMIT TÚLLÉPVE",
                        font=("Segoe UI", 9, "bold"),
                        bg=card_bg,
                        fg="#DC2626",
                    )
                    warn_lbl.pack(side=tk.LEFT, padx=10)

                stat_frame = tk.Frame(info_frame, bg=card_bg)
                stat_frame.pack(fill=tk.X, pady=(6, 0))

                s1 = tk.Label(
                    stat_frame,
                    text=f"🐟 Összes fogás: {count_val} db",
                    font=("Segoe UI", 9),
                    bg=card_bg,
                    fg="#475569",
                )
                s1.pack(side=tk.LEFT, padx=(0, 20))

                s2 = tk.Label(
                    stat_frame,
                    text=f"⚖️ Súly: {weight_val:.1f} kg",
                    font=("Segoe UI", 9),
                    bg=card_bg,
                    fg="#475569",
                )
                s2.pack(side=tk.LEFT, padx=(0, 20))

                if kk_weight > 0:
                    s3 = tk.Label(
                        stat_frame,
                        text=f"🪱 Fehérhal: {kk_weight:.1f} kg",
                        font=("Segoe UI", 9, "bold"),
                        bg=card_bg,
                        fg="#0284C7",
                    )
                    s3.pack(side=tk.LEFT)

                btn_naplo = tk.Button(
                    card,
                    text="📖 Egyéni napló ›",
                    font=("Segoe UI", 9, "bold"),
                    bg="#DC2626",
                    fg="white",
                    activebackground="#B91C1C",
                    activeforeground="white",
                    bd=0,
                    padx=14,
                    pady=8,
                    cursor="hand2",
                    command=lambda n=h_nev: self.open_egyeni_naplo_dialog(n),
                )
                btn_naplo.pack(side=tk.RIGHT, padx=5)

                for w in [card, mono_frame, mono_lbl, info_frame, name_row, name_lbl, stat_frame, s1, s2]:
                    if not self.is_archived:
                        w.bind(
                            "<Double-Button-1>",
                            lambda e, n=h_nev: self.open_quick_fogas_dialog(n),
                        )
                    w.bind(
                        "<Button-1>",
                        lambda e, n=h_nev: self.select_card_nev(n),
                    )

    def select_card_nev(self, nev):
        self.selected_card_nev = nev

    def add_horgasz_prompt(self):
        if self.is_archived:
            return
        nev = simpledialog.askstring(
            "Ember felvétele", "Adja meg az új horgász nevét:", parent=self.root
        )
        if nev and nev.strip():
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO horgaszok (nev) VALUES (?)", (nev.strip(),)
                )
                conn.commit()
                messagebox.showinfo("Siker", f"'{nev.strip()}' hozzáadva!")
                self.load_emberek_cards()
            except sqlite3.IntegrityError:
                messagebox.showerror("Hiba", "Ez a név már létezik!")
            finally:
                conn.close()

    def delete_horgasz_prompt(self):
        if self.is_archived:
            return
        target_nev = self.selected_card_nev
        if not target_nev:
            target_nev = simpledialog.askstring(
                "Ember eltávolítása",
                "Adja meg a törlendő horgász pontos nevét:",
                parent=self.root,
            )

        if not target_nev:
            return

        if messagebox.askyesno(
            "Megerősítés",
            f"Biztosan törölni szeretnéd '{target_nev}' horgászt és az ÖSSZES adatát?",
        ):
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM horgaszok WHERE nev = ?", (target_nev,))
            res = cursor.fetchone()
            if res:
                h_id = res[0]
                cursor.execute("DELETE FROM fogasok WHERE horgasz_id = ?", (h_id,))
                cursor.execute("DELETE FROM horgaszok WHERE id = ?", (h_id,))
                conn.commit()
                messagebox.showinfo("Siker", f"'{target_nev}' törölve lett!")
                self.selected_card_nev = None
                self.load_emberek_cards()
            else:
                messagebox.showerror("Hiba", "Ilyen nevű horgász nem található!")
            conn.close()

    def open_quick_fogas_dialog(self, default_nev):
        if self.is_archived:
            return
        self.clear_page()
        self.top_red_bar.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(
            self.top_red_bar,
            text=f"🐟 Fogás rögzítése — {default_nev}",
            font=("Segoe UI", 12, "bold"),
            bg="#DC2626",
            fg="white",
        )
        title_lbl.pack(side=tk.LEFT, padx=(15, 20), pady=10)

        bg_canvas = tk.Canvas(self.page_frame, bg="#111111", highlightthickness=0)
        bg_canvas.pack(fill=tk.BOTH, expand=True)

        def draw_gradient_background(event=None):
            bg_canvas.delete("gradient")
            w = max(self.page_frame.winfo_width(), 900)
            h = max(self.page_frame.winfo_height(), 600)
            
            steps = 50
            for i in range(steps):
                r = int(220 * (1 - i / steps))
                g = int(38 * (1 - i / steps))
                directive_color = f"#{r:02x}{g:02x}{g:02x}"
                y1 = (h / steps) * i
                y2 = (h / steps) * (i + 1)
                bg_canvas.create_rectangle(0, y1, w, y2, fill=directive_color, outline="", tags="gradient")
            
            bg_canvas.tag_raise("card_window")

        bg_canvas.bind("<Configure>", draw_gradient_background)

        card_outer = tk.Frame(bg_canvas, bg="#FFFFFF", bd=0)
        form_inner = tk.Frame(card_outer, bg="#FFFFFF", padx=35, pady=30)
        form_inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(form_inner, text="🐟", font=("Segoe UI", 22), bg="#FFFFFF", fg="#2563EB").pack(pady=(0, 2))
        tk.Label(form_inner, text="Fogás hozzáadása", font=("Segoe UI", 14, "bold"), bg="#FFFFFF", fg="#1E293B").pack()
        tk.Label(form_inner, text="Új fogás rögzítése", font=("Segoe UI", 14), bg="#FFFFFF", fg="#647488").pack(pady=(0, 15))

        def add_field(label_str, val="", readonly=False):
            tk.Label(form_inner, text=label_str, font=("Segoe UI", 7, "bold"), bg="#FFFFFF", fg="#64748B", anchor="w").pack(fill=tk.X)
            if readonly:
                f_box = tk.Frame(form_inner, bg="#F8FAFC", bd=1, relief="solid")
                f_box.pack(fill=tk.X, pady=(2, 12))
                lbl = tk.Label(f_box, text=val, font=("Segoe UI", 9), bg="#F8FAFC", fg="#334155", anchor="w", padx=8, pady=6)
                lbl.pack(fill=tk.X)
                return lbl
            else:
                ent = ttk.Entry(form_inner, font=("Segoe UI", 9))
                ent.pack(fill=tk.X, pady=(2, 12), ipady=3)
                if val:
                    ent.insert(0, val)
                return ent

        add_field("NÉV", default_nev, readonly=True)
        
        now_dt = datetime.datetime.now()
        default_date_str = f"{now_dt.month:02d} {now_dt.day:02d}"
        dat_ent = add_field("DÁTUM", default_date_str)

        tk.Label(form_inner, text="FAJTA", font=("Segoe UI", 7, "bold"), bg="#FFFFFF", fg="#64748B", anchor="w").pack(fill=tk.X)
        all_halak, _, _ = get_halfaj_tipusok(self.db_name)
        hal_cb = ttk.Combobox(form_inner, values=all_halak, state="readonly", font=("Segoe UI", 9))
        hal_cb.pack(fill=tk.X, pady=(2, 12), ipady=3)
        if "Ponty" in all_halak:
            hal_cb.set("Ponty")
        elif all_halak:
            hal_cb.set(all_halak[0])

        kg_ent = add_field("SÚLY (KG)", "")

        def save_quick_fogas():
            datum_str = dat_ent.get().strip()
            hal = hal_cb.get()
            kg_text = kg_ent.get().strip()

            if not datum_str or not kg_text:
                messagebox.showerror("Hiba", "Minden mezőt tölts ki!")
                return

            current_year = datetime.datetime.now().year
            try:
                clean_date = datum_str.replace(".", " ").strip()
                parts = clean_date.split()
                if len(parts) >= 2:
                    m, d = int(parts[0]), int(parts[1])
                else:
                    raise ValueError("Helytelen dátum")

                parsed_time = datetime.date(current_year, m, d)
                full_datum_str = parsed_time.strftime("%Y-%m-%d")
                datum_obj = parsed_time
            except ValueError:
                messagebox.showerror("Hiba", "Érvénytelen dátum formátum!")
                return

            try:
                kg = float(kg_text.replace(",", "."))
            except ValueError:
                messagebox.showerror("Hiba", "A súlynak számnak kell lennie!")
                return

            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM horgaszok WHERE nev = ?", (default_nev,))
            horgasz_id = cursor.fetchone()[0]

            settings = get_settings(self.db_name)
            max_keszeg = settings.get("keszeg_limit", 10.0)

            _, eves_halak, feherhalak = get_halfaj_tipusok(self.db_name)

            warning_msg = None
            if hal in feherhalak:
                placeholders = ','.join(['?'] * len(feherhalak)) if feherhalak else "'__DUMMY__'"
                cursor.execute(f"""
                    SELECT SUM(kg) FROM fogasok WHERE horgasz_id = ? AND hal_fajta IN ({placeholders}) AND strftime('%Y', datum) = ?
                """, [horgasz_id] + feherhalak + [str(current_year)])
                res = cursor.fetchone()[0]
                current_feher_kg = res if res else 0.0
                if current_feher_kg + kg > max_keszeg:
                    warning_msg = f"FIGYELEM! A fehérhal éves limitje ({max_keszeg} kg) túllépésre került!"
            elif hal in eves_halak:
                q_name, q_limit, q_start, q_end = get_quarter_for_date(datum_obj, self.db_name)
                if q_name and q_limit is not None:
                    cursor.execute("SELECT datum FROM fogasok WHERE horgasz_id = ? AND hal_fajta = ?", (horgasz_id, hal))
                    count = 0
                    for rec_d_str, in cursor.fetchall():
                        r_date = datetime.datetime.strptime(rec_d_str, "%Y-%m-%d").date()
                        if check_date_in_quarter(r_date, q_start, q_end):
                            count += 1
                    if count + 1 > q_limit:
                        warning_msg = f"FIGYELEM! A(z) {q_name} negyedéves limit ({q_limit} db) túllépésre került!"

            cursor.execute(
                "INSERT INTO fogasok (horgasz_id, datum, hal_fajta, kg) VALUES (?, ?, ?, ?)",
                (horgasz_id, full_datum_str, hal, kg),
            )
            conn.commit()
            conn.close()

            # --- ITT JELENIK MEG A FELUGRÓ ÜZENET, HA TÚLLÉPTÉK A LIMITET ---
            if warning_msg:
                messagebox.showwarning("⚠️ LIMIT TÚLLÉPÉS FIGYELMEZTETÉS", f"{warning_msg}\n\nA fogás ettől függetlenül elmentésre került.")
            else:
                messagebox.showinfo("Siker", "Fogás elmentve!")

            self.show_emberek_page()

        save_btn = tk.Button(
            form_inner,
            text="➕ Fogás mentése",
            font=("Segoe UI", 9, "bold"),
            bg="#DC2626",
            fg="#FFFFFF",
            activebackground="#B91C1C",
            activeforeground="#FFFFFF",
            bd=0,
            pady=8,
            cursor="hand2",
            command=save_quick_fogas
        )
        save_btn.pack(fill=tk.X, pady=(10, 5))

        cancel_btn = tk.Button(
            form_inner,
            text="Mégsem",
            font=("Segoe UI", 9),
            bg="#FFFFFF",
            fg="#64748B",
            activebackground="#F1F5F9",
            activeforeground="#0F172A",
            bd=1,
            relief="solid",
            pady=6,
            cursor="hand2",
            command=self.show_emberek_page
        )
        cancel_btn.pack(fill=tk.X)

        card_window = bg_canvas.create_window(0, 0, window=card_outer, anchor="center", tags="card_window")

        def center_card(event=None):
            w = bg_canvas.winfo_width()
            h = bg_canvas.winfo_height()
            bg_canvas.coords(card_window, w / 2, h / 2)

        bg_canvas.bind("<Configure>", lambda e: [draw_gradient_background(e), center_card(e)])

    def open_egyeni_naplo_dialog(self, default_nev):
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Egyéni Fogási Napló - {default_nev}")
        dialog.geometry("600x420")
        dialog.configure(bg="#F1F5F9")
        dialog.grab_set()

        top_frame = tk.Frame(dialog, bg="#F1F5F9", padx=15, pady=10)
        top_frame.pack(fill=tk.X)

        tk.Label(
            top_frame,
            text=f"📖 {default_nev} fogási naplója",
            font=("Segoe UI", 11, "bold"),
            bg="#F1F5F9",
            fg="#0F172A",
        ).pack(side=tk.LEFT)

        tree_frame = tk.Frame(dialog)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        tree = ttk.Treeview(
            tree_frame,
            columns=("id", "datum", "hal", "kg"),
            show="headings",
            style="RedHeader.Treeview",
        )
        tree.heading("datum", text="DÁTUM")
        tree.heading("hal", text="HAL FAJTA")
        tree.heading("kg", text="SÚLY (KG)")
        tree.column("id", width=0, stretch=False)
        tree.column("datum", width=120, anchor="center")
        tree.column("hal", width=220, anchor="w")
        tree.column("kg", width=120, anchor="center")

        scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True)

        tree.tag_configure("limit_exceeded", background="#FECDD3")

        def load_log():
            for item in tree.get_children():
                tree.delete(item)

            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM horgaszok WHERE nev = ?", (default_nev,)
            )
            res = cursor.fetchone()
            if not res:
                conn.close()
                return

            horgasz_id = res[0]
            cursor.execute(
                "SELECT id, datum, hal_fajta, kg FROM fogasok WHERE horgasz_id = ? ORDER BY datum ASC, id ASC",
                (horgasz_id,),
            )
            rows = cursor.fetchall()
            conn.close()

            settings = get_settings(self.db_name)
            max_keszeg = settings.get("keszeg_limit", 10.0)
            current_year = datetime.datetime.now().year

            _, eves_halak, feherhalak = get_halfaj_tipusok(self.db_name)

            feher_cum_kg = 0.0
            q_counts = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}

            for r_id, r_datum, r_hal, r_kg in rows:
                r_date_obj = datetime.datetime.strptime(
                    r_datum, "%Y-%m-%d"
                ).date()
                is_exceeded = False

                if r_hal in feherhalak:
                    if r_date_obj.year == current_year:
                        feher_cum_kg += r_kg
                        if feher_cum_kg > max_keszeg:
                            is_exceeded = True
                elif r_hal in eves_halak:
                    q_name, q_lim, q_start, q_end = get_quarter_for_date(
                        r_date_obj, self.db_name
                    )
                    if q_name and q_lim is not None:
                        q_counts[q_name] += 1
                        if q_counts[q_name] > q_lim:
                            is_exceeded = True

                tags = ("limit_exceeded",) if is_exceeded else ()
                tree.insert(
                    "",
                    tk.END,
                    values=(r_id, r_datum[5:], r_hal, f"{r_kg:.1f}".replace(".", ",")),
                    tags=tags,
                )

        def delete_item():
            if self.is_archived:
                messagebox.showwarning("Figyelem", "Archív módban nem lehet törölni!", parent=dialog)
                return
            selected = tree.selection()
            if not selected:
                messagebox.showwarning(
                    "Figyelem", "Válassz ki egy törlendő elemet!", parent=dialog
                )
                return
            item_values = tree.item(selected[0], "values")

            if messagebox.askyesno(
                "Megerősítés",
                "Biztosan törlöd a kijelölt rekordot?",
                parent=dialog,
            ):
                conn = self.get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM fogasok WHERE id = ?", (item_values[0],)
                )
                conn.commit()
                conn.close()
                load_log()
                self.load_emberek_cards()

        if not self.is_archived:
            btn_frame = tk.Frame(dialog, bg="#F1F5F9", pady=10)
            btn_frame.pack(fill=tk.X)

            ttk.Button(
                btn_frame,
                text="❌ Kijelölt Rekord Törlése",
                command=delete_item,
            ).pack()

        load_log()

    def show_osszesites_page(self):
        self.setActiveMenu("osszesites")
        self.clear_page()

        header_bar = tk.Frame(self.page_frame, bg="#DC2626", height=45)
        header_bar.pack(fill=tk.X)

        tk.Label(
            header_bar,
            text="📊 Összegző",
            font=("Segoe UI", 12, "bold"),
            bg="#DC2626",
            fg="white",
        ).pack(side=tk.LEFT, padx=15, pady=10)

        content_bg = tk.Frame(self.page_frame, bg="#F1F5F9", padx=15, pady=15)
        content_bg.pack(fill=tk.BOTH, expand=True)

        tree_frame = tk.Frame(content_bg, bg="white", bd=1, relief="solid")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)

        all_species, eves_halak, feherhalak = get_halfaj_tipusok(self.db_name)
        std_species = [s for s in eves_halak]
        for s in all_species:
            if s not in std_species and s not in feherhalak:
                std_species.append(s)

        cols = ["nev"]
        for sp in std_species:
            cols.extend([f"{sp}_db", f"{sp}_kg"])
        
        for fh in feherhalak:
            cols.append(f"{fh}_kg")

        cols.extend(["e_db", "e_kg"])

        tree = ttk.Treeview(
            tree_frame,
            columns=cols,
            show="headings",
            style="RedHeader.Treeview",
            xscrollcommand=scroll_x.set,
            yscrollcommand=scroll_y.set,
        )

        scroll_x.config(command=tree.xview)
        scroll_y.config(command=tree.yview)
        scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(fill=tk.BOTH, expand=True)

        tree.heading("nev", text="HORGÁSZ")
        tree.column("nev", width=130, anchor="w")

        for i, sp in enumerate(std_species):
            for suffix, label_s in [("_db", " DB"), ("_kg", " KG")]:
                col_key = f"{sp}{suffix}"
                tree.heading(col_key, text=f"{sp.upper()}{label_s}")
                tree.column(col_key, width=75, anchor="center")

        for fh in feherhalak:
            col_key = f"{fh}_kg"
            tree.heading(col_key, text=f"{fh.upper()} KG")
            tree.column(col_key, width=80, anchor="center")

        tree.heading("e_db", text="EGYÉB DB")
        tree.heading("e_kg", text="EGYÉB KG")
        tree.column("e_db", width=75, anchor="center")
        tree.column("e_kg", width=75, anchor="center")

        tree.tag_configure("even_row", background="#FFFFFF")
        tree.tag_configure("odd_row", background="#FAFAFA")

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, nev FROM horgaszok ORDER BY nev ASC")
        horgaszok = cursor.fetchall()

        for i, (h_id, h_nev) in enumerate(horgaszok):
            row = [f" {h_nev}"]

            for sp in std_species:
                cursor.execute(
                    "SELECT COUNT(*), SUM(kg) FROM fogasok WHERE horgasz_id = ? AND hal_fajta = ?",
                    (h_id, sp),
                )
                c, k = cursor.fetchone()
                c_val = c if c else 0
                k_val = f"{k:.1f}".replace(".", ",") if k else "0"
                row.extend([c_val, k_val])

            for fh in feherhalak:
                cursor.execute(
                    "SELECT SUM(kg) FROM fogasok WHERE horgasz_id = ? AND hal_fajta = ?",
                    (h_id, fh),
                )
                k_fh = cursor.fetchone()[0]
                row.append(f"{k_fh:.1f}".replace(".", ",") if k_fh else "0")

            excluded_fajok = std_species + feherhalak
            placeholders = ','.join(['?'] * len(excluded_fajok)) if excluded_fajok else "'__DUMMY__'"
            cursor.execute(
                f"SELECT COUNT(*), SUM(kg) FROM fogasok WHERE horgasz_id = ? AND hal_fajta NOT IN ({placeholders})",
                [h_id] + excluded_fajok,
            )
            c_e, k_e = cursor.fetchone()
            row.extend(
                [c_e if c_e else 0, f"{k_e:.1f}".replace(".", ",") if k_e else "0"]
            )

            tag = "even_row" if i % 2 == 0 else "odd_row"
            tree.insert("", tk.END, values=row, tags=(tag,))

        conn.close()

    def show_ranglista_page(self):
        self.setActiveMenu("ranglista")
        self.clear_page()

        header_bar = tk.Frame(self.page_frame, bg="#DC2626", height=45)
        header_bar.pack(fill=tk.X)

        tk.Label(
            header_bar,
            text="🏆 Ranglista",
            font=("Segoe UI", 12, "bold"),
            bg="#DC2626",
            fg="white",
        ).pack(side=tk.LEFT, padx=15, pady=10)

        notebook = ttk.Notebook(self.page_frame, style="Red.TNotebook")
        notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        weight_tab = ttk.Frame(notebook)
        notebook.add(weight_tab, text="⚖️ Legtöbb Súly (kg)")

        tree_weight = ttk.Treeview(
            weight_tab,
            columns=("helyezes", "nev", "tot_kg", "tot_db"),
            show="headings",
            style="RedHeader.Treeview",
        )
        tree_weight.heading("helyezes", text="HELYEZÉS")
        tree_weight.heading("nev", text="HORGÁSZ NEVE")
        tree_weight.heading("tot_kg", text="ÖSSZESEN SÚLY (KG)")
        tree_weight.heading("tot_db", text="ÖSSZESEN HAL (DB)")

        tree_weight.column("helyezes", width=100, anchor="center")
        tree_weight.column("nev", width=250, anchor="w")
        tree_weight.column("tot_kg", width=150, anchor="center")
        tree_weight.column("tot_db", width=150, anchor="center")
        tree_weight.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        count_tab = ttk.Frame(notebook)
        notebook.add(count_tab, text="🐟 Legtöbb Fogás (db)")

        tree_count = ttk.Treeview(
            count_tab,
            columns=("helyezes", "nev", "tot_db", "tot_kg"),
            show="headings",
            style="RedHeader.Treeview",
        )
        tree_count.heading("helyezes", text="HELYEZÉS")
        tree_count.heading("nev", text="HORGÁSZ NEVE")
        tree_count.heading("tot_db", text="ÖSSZESEN HAL (DB)")
        tree_count.heading("tot_kg", text="ÖSSZESEN SÚLY (KG)")

        tree_count.column("helyezes", width=100, anchor="center")
        tree_count.column("nev", width=250, anchor="w")
        tree_count.column("tot_db", width=150, anchor="center")
        tree_count.column("tot_kg", width=150, anchor="center")
        tree_count.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        for tree in (tree_weight, tree_count):
            tree.tag_configure(
                "top1",
                background="#FCA5A5",
                font=("Segoe UI", 9, "bold"),
                foreground="#7F1D1D",
            )
            tree.tag_configure(
                "top2",
                background="#FECDD3",
                font=("Segoe UI", 9, "bold"),
                foreground="#881337",
            )
            tree.tag_configure(
                "top3",
                background="#FFE4E6",
                font=("Segoe UI", 9, "bold"),
                foreground="#9F1239",
            )

        conn = self.get_db_connection()
        cursor = conn.cursor()

        _, _, feherhalak = get_halfaj_tipusok(self.db_name)
        placeholders = ','.join(['?'] * len(feherhalak)) if feherhalak else "'__DUMMY__'"

        if feherhalak:
            cursor.execute(f"""
                SELECT h.nev, COALESCE(SUM(f.kg), 0) as ossz_kg, COALESCE(COUNT(f.id), 0) as ossz_db
                FROM horgaszok h
                LEFT JOIN fogasok f ON h.id = f.horgasz_id AND f.hal_fajta NOT IN ({placeholders})
                GROUP BY h.id, h.nev
                ORDER BY ossz_kg DESC, ossz_db DESC
            """, feherhalak)
        else:
            cursor.execute("""
                SELECT h.nev, COALESCE(SUM(f.kg), 0) as ossz_kg, COALESCE(COUNT(f.id), 0) as ossz_db
                FROM horgaszok h
                LEFT JOIN fogasok f ON h.id = f.horgasz_id
                GROUP BY h.id, h.nev
                ORDER BY ossz_kg DESC, ossz_db DESC
            """)
        weight_rows = cursor.fetchall()

        for idx, (nev, kg, db) in enumerate(weight_rows, start=1):
            tag = "top1" if idx == 1 else ("top2" if idx == 2 else ("top3" if idx == 3 else ""))
            pos_str = f"🥇 1." if idx == 1 else (f"🥈 2." if idx == 2 else (f"🥉 3." if idx == 3 else f"{idx}."))
            tree_weight.insert(
                "",
                tk.END,
                values=(
                    pos_str,
                    nev,
                    f"{kg:.1f}".replace(".", ",") + " kg",
                    f"{db} db",
                ),
                tags=(tag,) if tag else (),
            )

        if feherhalak:
            cursor.execute(f"""
                SELECT h.nev, COALESCE(COUNT(f.id), 0) as ossz_db, COALESCE(SUM(f.kg), 0) as ossz_kg
                FROM horgaszok h
                LEFT JOIN fogasok f ON h.id = f.horgasz_id AND f.hal_fajta NOT IN ({placeholders})
                GROUP BY h.id, h.nev
                ORDER BY ossz_db DESC, ossz_kg DESC
            """, feherhalak)
        else:
            cursor.execute("""
                SELECT h.nev, COALESCE(COUNT(f.id), 0) as ossz_db, COALESCE(SUM(f.kg), 0) as ossz_kg
                FROM horgaszok h
                LEFT JOIN fogasok f ON h.id = f.horgasz_id
                GROUP BY h.id, h.nev
                ORDER BY ossz_db DESC, ossz_kg DESC
            """)
        count_rows = cursor.fetchall()

        for idx, (nev, db, kg) in enumerate(count_rows, start=1):
            tag = "top1" if idx == 1 else ("top2" if idx == 2 else ("top3" if idx == 3 else ""))
            pos_str = f"🥇 1." if idx == 1 else (f"🥈 2." if idx == 2 else (f"🥉 3." if idx == 3 else f"{idx}."))
            tree_count.insert(
                "",
                tk.END,
                values=(
                    pos_str,
                    nev,
                    f"{db} db",
                    f"{kg:.1f}".replace(".", ",") + " kg",
                ),
                tags=(tag,) if tag else (),
            )

        conn.close()

    def show_negyedevek_page(self):
        if self.is_archived:
            return
        self.setActiveMenu("negyedevek")
        self.clear_page()

        header_bar = tk.Frame(self.page_frame, bg="#DC2626", height=45)
        header_bar.pack(fill=tk.X)

        tk.Label(
            header_bar,
            text="📅 Negyedévek és Korlátok beállítása",
            font=("Segoe UI", 12, "bold"),
            bg="#DC2626",
            fg="white",
        ).pack(side=tk.LEFT, padx=15, pady=10)

        card = tk.Frame(self.page_frame, bg="#ffffff", padx=20, pady=20)
        card.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)

        settings = get_settings(self.db_name)
        entries = {}

        headers = ["Negyedév / Típus", "Kezdet (HH-NN)", "Vég (HH-NN)", "Limit (db / kg)"]
        for col_idx, h in enumerate(headers):
            tk.Label(
                card,
                text=h,
                font=("Segoe UI", 10, "bold"),
                bg="#ffffff",
                fg="#DC2626",
            ).grid(row=0, column=col_idx, padx=10, pady=10)

        for row_idx, q_key in enumerate(["Q1", "Q2", "Q3", "Q4"], start=1):
            tk.Label(
                card,
                text=f"{q_key} (¼ év):",
                font=("Segoe UI", 10, "bold"),
                bg="#ffffff",
            ).grid(row=row_idx, column=0, padx=10, pady=10, sticky="w")

            e_start = ttk.Entry(card, width=12)
            e_start.grid(row=row_idx, column=1, padx=10, pady=10)
            e_start.insert(0, settings[q_key]["start"])

            e_end = ttk.Entry(card, width=12)
            e_end.grid(row=row_idx, column=2, padx=10, pady=10)
            e_end.insert(0, settings[q_key]["end"])

            e_lim = ttk.Entry(card, width=10)
            e_lim.grid(row=row_idx, column=3, padx=10, pady=10)
            e_lim.insert(0, str(settings[q_key]["limit"]))

            entries[q_key] = {"start": e_start, "end": e_end, "limit": e_lim}

        row_idx_k = 5
        tk.Label(
            card,
            text="Fehérhal éves limit (kg):",
            font=("Segoe UI", 10, "bold"),
            bg="#ffffff",
            fg="#0284C7"
        ).grid(row=row_idx_k, column=0, padx=10, pady=15, sticky="w")

        e_keszeg_lim = ttk.Entry(card, width=10)
        e_keszeg_lim.grid(row=row_idx_k, column=3, padx=10, pady=15)
        e_keszeg_lim.insert(0, str(settings.get("keszeg_limit", 10.0)))
        entries["keszeg_limit"] = e_keszeg_lim

        def save_settings():
            conn = self.get_db_connection()
            cursor = conn.cursor()
            try:
                k_lim_val = float(entries["keszeg_limit"].get().strip().replace(",", "."))
                cursor.execute(
                    """
                    UPDATE beallitasok SET
                    q1_start=?, q1_end=?, q1_limit=?,
                    q2_start=?, q2_end=?, q2_limit=?,
                    q3_start=?, q3_end=?, q3_limit=?,
                    q4_start=?, q4_end=?, q4_limit=?,
                    keszeg_limit=?
                    WHERE id = 1
                """,
                    (
                        entries["Q1"]["start"].get().strip(),
                        entries["Q1"]["end"].get().strip(),
                        int(entries["Q1"]["limit"].get().strip()),
                        entries["Q2"]["start"].get().strip(),
                        entries["Q2"]["end"].get().strip(),
                        int(entries["Q2"]["limit"].get().strip()),
                        entries["Q3"]["start"].get().strip(),
                        entries["Q3"]["end"].get().strip(),
                        int(entries["Q3"]["limit"].get().strip()),
                        entries["Q4"]["start"].get().strip(),
                        entries["Q4"]["end"].get().strip(),
                        int(entries["Q4"]["limit"].get().strip()),
                        k_lim_val
                    ),
                )
                conn.commit()
                messagebox.showinfo("Siker", "Beállítások elmentve!")
            except ValueError:
                messagebox.showerror("Hiba", "Érvényes számokat adj meg a limitekhez!")
            except Exception as e:
                messagebox.showerror("Hiba", f"Hiba: {e}")
            finally:
                conn.close()

        ttk.Button(
            card, text="Beállítások Mentése", command=save_settings
        ).grid(row=6, column=3, pady=20, sticky="e")

    def show_elozetes_evek_page(self):
        if self.is_archived:
            return
        self.setActiveMenu("eloz_evek")
        self.clear_page()

        header_bar = tk.Frame(self.page_frame, bg="#DC2626", height=45)
        header_bar.pack(fill=tk.X)

        tk.Label(
            header_bar,
            text="📁 Előző évek archívuma",
            font=("Segoe UI", 12, "bold"),
            bg="#DC2626",
            fg="white",
        ).pack(side=tk.LEFT, padx=15, pady=10)

        content_bg = tk.Frame(self.page_frame, bg="#F1F5F9", padx=20, pady=20)
        content_bg.pack(fill=tk.BOTH, expand=True)

        list_frame = tk.Frame(content_bg, bg="white", bd=1, relief="solid")
        list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        listbox = tk.Listbox(list_frame, font=("Segoe UI", 11), yscrollcommand=scrollbar.set, bd=0, highlightthickness=0)
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        scrollbar.config(command=listbox.yview)

        evek_dir = "evek"
        if not os.path.exists(evek_dir):
            os.makedirs(evek_dir)

        def refresh_list():
            listbox.delete(0, tk.END)
            files = [f for f in os.listdir(evek_dir) if f.endswith(".db")]
            for f in sorted(files):
                listbox.insert(tk.END, f)

        refresh_list()

        btn_panel = tk.Frame(content_bg, bg="#F1F5F9", width=200)
        btn_panel.pack(side=tk.RIGHT, fill=tk.Y)

        def open_selected_year():
            sel = listbox.curselection()
            if not sel:
                messagebox.showwarning("Figyelem", "Válassz ki egy évet a listából!")
                return
            filename = listbox.get(sel[0])
            full_path = os.path.join("evek", filename)
            
            new_win = tk.Toplevel(self.root)
            HorgaszApp(new_win, db_name=full_path, is_archived=True)

        def rename_selected_year():
            sel = listbox.curselection()
            if not sel:
                messagebox.showwarning("Figyelem", "Válassz ki egy évet az átnevezéshez!")
                return
            old_filename = listbox.get(sel[0])
            
            new_name = simpledialog.askstring("Átnevezés", "Add meg az új nevet (pl. 2025_zaras.db):", initialvalue=old_filename, parent=self.root)
            if new_name and new_name.strip():
                if not new_name.endswith(".db"):
                    new_name += ".db"
                old_path = os.path.join("evek", old_filename)
                new_path = os.path.join("evek", new_name.strip())
                try:
                    os.rename(old_path, new_path)
                    refresh_list()
                    messagebox.showinfo("Siker", "Fájl sikeresen átnevezve!")
                except Exception as e:
                    messagebox.showerror("Hiba", f"Nem sikerült átnevezni: {e}")

        def delete_selected_year():
            sel = listbox.curselection()
            if not sel:
                messagebox.showwarning("Figyelem", "Válassz ki egy évet a törléshez!")
                return
            filename = listbox.get(sel[0])
            
            ans1 = messagebox.askyesno("⚠️ Biztos törlöd?", f"Biztosan törölni szeretnéd a(z) '{filename}' évet?", parent=self.root)
            if not ans1: return
            
            ans2 = messagebox.askyesno("🚨 Végleges törlés!", f"Ez a művelet nem vonható vissza! Biztosan törlöd az archívumot?", parent=self.root)
            if not ans2: return

            conf = simpledialog.askstring("🛑 Utolsó megerősítés", "Írd be a törlés megerősítéséhez: TORLES", parent=self.root)
            if conf and conf.strip().upper() == "TORLES":
                try:
                    os.remove(os.path.join("evek", filename))
                    refresh_list()
                    messagebox.showinfo("Siker", "Az archív év törölve lett.")
                except Exception as e:
                    messagebox.showerror("Hiba", f"Hiba történt: {e}")
            else:
                messagebox.showwarning("Megszakítva", "A megerősítő kód nem egyezett.")

        tk.Button(btn_panel, text="📂 Adott év megnyitása", font=("Segoe UI", 9, "bold"), bg="#2563EB", fg="white", bd=0, padx=10, pady=8, command=open_selected_year).pack(fill=tk.X, pady=5)
        tk.Button(btn_panel, text="✏️ Év átnevezése", font=("Segoe UI", 9, "bold"), bg="#D97706", fg="white", bd=0, padx=10, pady=8, command=rename_selected_year).pack(fill=tk.X, pady=5)
        tk.Button(btn_panel, text="🗑️ Év törlése", font=("Segoe UI", 9, "bold"), bg="#DC2626", fg="white", bd=0, padx=10, pady=8, command=delete_selected_year).pack(fill=tk.X, pady=5)

    def reset_new_year(self):
        if self.is_archived:
            return
        self.setActiveMenu("mentes")
        ans1 = messagebox.askyesno(
            "⚠️ ÚJ ÉV KEZDÉSE - 1. Megerősítés",
            "Biztosan el akarod indítani az ÚJ ÉV KEZDÉSE folyamatot?\n\nA jelenlegi adatok átmentődnek az 'evek' mappába, és a naplók kiürülnek!",
        )
        if not ans1:
            return

        ans2 = messagebox.askyesno(
            "🚨 FIGYELEM! ADATOK TÖRLÉSE - 2. Megerősítés",
            "A jelenlegi fogási naplók kiürülnek az új évhez!\n\nValóban folytatni szeretnéd?",
        )
        if not ans2:
            return

        confirm_text = simpledialog.askstring(
            "🛑 UTOLSÓ BIZTONSÁGI LÉPÉS",
            "Írd be a szót: ÚJÉV",
            parent=self.root,
        )

        if confirm_text and confirm_text.strip().upper() == "ÚJÉV":
            now_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            current_year_str = str(datetime.datetime.now().year)
            
            if not os.path.exists("evek"):
                os.makedirs("evek")

            archived_db_path = os.path.join("evek", f"{current_year_str}_ev_zarva_{now_str}.db")
            try:
                shutil.copy2("horgaszat.db", archived_db_path)
            except Exception as e:
                messagebox.showerror("Mentési Hiba", f"Hiba: {e}")
                return

            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM fogasok;")
            conn.commit()
            conn.close()

            messagebox.showinfo("Siker!", f"Az újév kezdeti adatai frissítve lettek.\nA(z) {current_year_str} évi adatok elmentve az 'evek' mappába.")
            self.show_emberek_page()


if __name__ == "__main__":
    root = tk.Tk()
    app = HorgaszApp(root)
    root.mainloop()