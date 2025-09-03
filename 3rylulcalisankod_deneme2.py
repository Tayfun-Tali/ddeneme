import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pandas as pd
import os
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
import re

class DataAnalyzerApp:
    def __init__(self, master):
        self.master = master
        self.master.title("Strain Gauge Veri Analiz ve Görselleştirme Aracı")
        self.master.geometry("950x750")

        self.file_map = {}
        self.annot = None
        self.popup_info = {}
        
        # --- NİHAİ MİMARİ: TEK GERÇEKLİK KAYNAĞI & DURUM YÖNETİMİ ---
        self.original_df = None         # Tüm veriyi ve hesaplamaları tutan TEK DataFrame.
        self.prediction_df = None
        self.plotted_sgs = []           # Grafikte hangi SG'lerin çizileceğini tutan ana liste.
        self.is_view_trimmed = False    # Görünümün kesilmiş olup olmadığını tutan basit durum değişkeni.
        
        self.physical_sg_columns = []
        self.all_sg_columns = []
        self.shear_rosettes = {}
        self.average_pairs = {}

        self.calculations = {
            "Shear (S = 2B - A - C)": { "inputs": ['A', 'B', 'C'], "output_suffix": 'S', "formula": lambda A, B, C: 2 * B - A - C },
            "Average (Avg = (D+E)/2)": { "inputs": ['D', 'E'], "output_suffix": 'Avg', "formula": lambda D, E: (D + E) / 2 },
        }
        self.create_widgets()

    # --- MERKEZİ FONKSİYONLAR ---

    def get_display_df(self):
        """O an görüntülenmesi gereken DataFrame'i ana kaynaktan anlık olarak oluşturur."""
        if self.original_df is None: return None
        if self.is_view_trimmed:
            load_column = self._get_load_column()
            if load_column and load_column in self.original_df.columns:
                try:
                    max_load_index = self.original_df[load_column].idxmax()
                    return self.original_df.loc[:max_load_index]
                except ValueError:
                    return self.original_df
        return self.original_df

    def _redraw_all_plots(self):
        """
        Grafiği ve tabloyu SIFIRDAN çizen TEK sorumlu fonksiyondur.
        Hover'ı korur ve her zaman en güncel durumu yansıtır.
        """
        # 1. Hover'ı korumak için eksenleri temizlemeden sadece çizgileri sil
        while self.ax.lines: self.ax.lines[0].remove()
        if self.ax.get_legend() is not None: self.ax.get_legend().remove()
        
        # 2. O anki duruma göre doğru veriyi al (kesilmiş veya tam)
        display_df = self.get_display_df()
        
        # 3. Grafiği çiz
        if display_df is None or display_df.empty:
            self.ax.set_title("Grafik için veri yok veya yüklenmedi")
        else:
            x_column = self._get_load_column()
            if x_column:
                # `plotted_sgs` listesindeki her şeyi bu veriyle yeniden çiz
                for sg_name in self.plotted_sgs:
                    if sg_name in display_df.columns:
                        self.ax.plot(display_df[x_column], display_df[sg_name], marker='o', linestyle='-', label=sg_name)
                
                if self.prediction_df is not None:
                    self.ax.plot(self.prediction_df['Load'], self.prediction_df['Predicted_Strain'], marker='x', linestyle='--', label='Tahmini Değerler')

                # Grafiği ayarla
                if self.plotted_sgs or self.prediction_df is not None:
                    self.ax.legend()
                else:
                    self.ax.set_title(f"Yük Oranına Karşı Strain ({self.combo_id.get() or 'ID Seçilmedi'})")
                    self.ax.set_xlabel("Yük Oranı (%)"); self.ax.set_ylabel("Strain (μstrain)")
        
        self.ax.relim(); self.ax.autoscale_view(); self.ax.grid(True)
        self.canvas.draw()
        
        # 4. Tabloyu da bu yeni duruma göre senkronize et
        self._update_main_table()

    def _update_main_table(self):
        """Grafikte o an çizili olan TÜM strain gauge'leri ana tabloda gösterir."""
        if not self.plotted_sgs or self.original_df is None:
            self.guncelle_tablo(None); return
        load_column = self._get_load_column()
        if not load_column:
            self.guncelle_tablo(None); return
            
        columns_to_show = [load_column] + self.plotted_sgs
        try:
            # Ana DataFrame'den bu sütunları seçerek tabloyu güncelle
            self.guncelle_tablo(self.original_df[columns_to_show])
        except KeyError:
            # Olası bir hatada tabloyu temizle
            self.guncelle_tablo(None)

    # --- KULLANICI EYLEM FONKSİYONLARI (Sadece durumu değiştirip _redraw_all_plots'u çağırırlar) ---

    def grafige_ekle(self):
        selected_sg = self.combo_sg.get()
        if self.original_df is None or not selected_sg or selected_sg in self.plotted_sgs: return
        self.plotted_sgs.append(selected_sg)
        self._redraw_all_plots()
        self.sg_secildi() # Buton durumunu güncelle
        self.btn_trim.config(state="normal"); self.btn_reset_view.config(state="normal")
        self.lbl_durum.config(text=f"'{selected_sg}' eklendi."); self.notebook.select(0)

    def grafigden_cikar(self):
        selected_sg = self.combo_sg.get()
        if not selected_sg or selected_sg not in self.plotted_sgs: return
        self.plotted_sgs.remove(selected_sg)
        self._redraw_all_plots()
        self.sg_secildi() # Buton durumunu güncelle
        self.lbl_durum.config(text=f"'{selected_sg}' çıkarıldı.")

    def sadece_yuklemeyi_goster(self):
        if self.original_df is None: return
        self.is_view_trimmed = True
        self._redraw_all_plots()
        self.lbl_durum.config(text="Sadece yükleme gösteriliyor.")

    def tum_veriyi_goster(self):
        if self.original_df is None: return
        self.is_view_trimmed = False
        self._redraw_all_plots()
        self.lbl_durum.config(text="Tüm veri aralığı gösteriliyor.")

    def perform_calculation(self, calc_name):
        if self.original_df is None: return
        calculation = self.calculations.get(calc_name)
        formula, output_suffix = calculation["formula"], calculation["output_suffix"]
        gruplar = self.shear_rosettes if "Shear" in calc_name else self.average_pairs
        if not gruplar:
            messagebox.showwarning("Grup Bulunamadı", f"'{calc_name}' için uygun gruplar bulunamadı."); return
        calculated_count, newly_added_sgs = 0, []
        for prefix, gauges in gruplar.items():
            new_col_name = f"{prefix}{output_suffix}:{gauges.get('suffix', 'SG')}"
            if new_col_name in self.original_df.columns: continue
            try:
                input_data = {inp: self.original_df[gauges[inp]] for inp in calculation["inputs"]}
                self.original_df[new_col_name] = formula(**input_data)
                newly_added_sgs.append(new_col_name); calculated_count += 1
            except KeyError as e:
                print(f"Uyarı: {prefix} için {e} bulunamadı, atlanıyor.")
        if calculated_count > 0:
            self.all_sg_columns.extend(newly_added_sgs); self.filtrele_sg()
            self._redraw_all_plots()
            messagebox.showinfo("Başarılı", f"{calculated_count} adet '{calc_name}' sonucu hesaplandı.")
        else:
            messagebox.showinfo("Bilgi", "Hesaplanacak yeni veri bulunmuyor.")

    def grafigi_temizle(self):
        self.plotted_sgs.clear(); self.prediction_df = None; self.is_view_trimmed = False
        self._redraw_all_plots()
        self.ax.set_title("Grafik Temizlendi"); self.canvas.draw()
        if self.annot: self.annot.set_visible(False)
        self.btn_trim.config(state="disabled"); self.btn_reset_view.config(state="disabled")
        self.btn_plus.config(state="disabled"); self.btn_minus.config(state="disabled")
        state = "normal" if self.original_df is not None else "disabled"
        if hasattr(self, 'calculate_menubutton'): self.calculate_menubutton.config(state=state)
        self.lbl_durum.config(text="Grafik temizlendi.")

    def sg_secildi(self, event=None):
        selected_sg = self.combo_sg.get()
        if not selected_sg or self.original_df is None:
            self.btn_plus.config(state="disabled"); self.btn_minus.config(state="disabled"); return
        is_plotted = selected_sg in self.plotted_sgs
        self.btn_plus.config(state="disabled" if is_plotted else "normal")
        self.btn_minus.config(state="normal" if is_plotted else "disabled")
        self.lbl_durum.config(text=f"'{selected_sg}' seçildi.")
        
    # --- YARDIMCI VE ARAYÜZ FONKSİYONLARI (Genellikle Değişiklik Gerekmez) ---

    def create_widgets(self):
        main_frame = ttk.Frame(self.master, padding=10); main_frame.pack(fill=tk.BOTH, expand=True)
        kontrol_cerceve = ttk.LabelFrame(main_frame, text="Kontrol Paneli", padding=10); kontrol_cerceve.pack(fill=tk.X, pady=5)
        kontrol_cerceve.columnconfigure(1, weight=1); kontrol_cerceve.columnconfigure(3, weight=1)
        self.btn_dosya_sec = ttk.Button(kontrol_cerceve, text="Tek Dosya Seç", command=self.dosya_sec); self.btn_dosya_sec.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.btn_klasor_sec = ttk.Button(kontrol_cerceve, text="Veri Klasörü Seç", command=self.klasor_sec); self.btn_klasor_sec.grid(row=0, column=1, columnspan=3, padx=5, pady=5, sticky="ew")
        self.lbl_kaynak_yolu = ttk.Label(kontrol_cerceve, text="Dosya veya klasör seçilmedi..."); self.lbl_kaynak_yolu.grid(row=1, column=0, columnspan=4, padx=5, pady=5, sticky="w")
        lbl_id = ttk.Label(kontrol_cerceve, text="Dosya ID:"); lbl_id.grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.combo_id = ttk.Combobox(kontrol_cerceve, state="readonly", width=30); self.combo_id.grid(row=2, column=1, padx=5, pady=5, sticky="ew"); self.combo_id.bind("<<ComboboxSelected>>", self.id_secildi)
        lbl_sg_search = ttk.Label(kontrol_cerceve, text="Strain Gauge Ara:"); lbl_sg_search.grid(row=2, column=2, padx=(10, 5), pady=5, sticky="w")
        self.entry_search_sg = ttk.Entry(kontrol_cerceve); self.entry_search_sg.grid(row=2, column=3, padx=5, pady=5, sticky="ew"); self.entry_search_sg.bind("<KeyRelease>", self.filtrele_sg); self.entry_search_sg.bind("<Return>", self.on_search_enter)
        sg_frame = ttk.Frame(kontrol_cerceve); sg_frame.grid(row=3, column=2, columnspan=2, sticky="ew")
        lbl_sg = ttk.Label(sg_frame, text="Strain Gauge Seç:"); lbl_sg.pack(side=tk.LEFT, padx=(10, 5))
        self.combo_sg = ttk.Combobox(sg_frame, state="readonly"); self.combo_sg.pack(side=tk.LEFT, fill=tk.X, expand=True); self.combo_sg.bind("<<ComboboxSelected>>", self.sg_secildi)
        self.btn_plus = ttk.Button(sg_frame, text="+", command=self.grafige_ekle, width=3, state="disabled"); self.btn_plus.pack(side=tk.LEFT, padx=(5, 0))
        self.btn_minus = ttk.Button(sg_frame, text="-", command=self.grafigden_cikar, width=3, state="disabled"); self.btn_minus.pack(side=tk.LEFT, padx=(2, 0))
        self.btn_tahmin = ttk.Button(kontrol_cerceve, text="Tahmin Verisi Yükle (.dat)", command=self.tahmin_verisi_yukle); self.btn_tahmin.grid(row=4, column=0, padx=5, pady=10, sticky="ew")
        self.calculate_menubutton = ttk.Menubutton(kontrol_cerceve, text="Hesaplamalar", state="disabled"); self.calculate_menubutton.grid(row=4, column=1, padx=5, pady=10, sticky="ew")
        calc_menu = tk.Menu(self.calculate_menubutton, tearoff=0); self.calculate_menubutton["menu"] = calc_menu
        for calc_name in self.calculations: calc_menu.add_command(label=calc_name, command=lambda n=calc_name: self.perform_calculation(n))
        self.btn_temizle = ttk.Button(kontrol_cerceve, text="TÜM GRAFİĞİ TEMİZLE", command=self.grafigi_temizle); self.btn_temizle.grid(row=4, column=2, columnspan=2, padx=5, pady=10, sticky="ew")
        self.btn_popup = ttk.Button(kontrol_cerceve, text="Grafiği Ayrı Pencerede Aç", command=self.grafik_popup); self.btn_popup.grid(row=5, column=0, padx=5, pady=5, sticky="ew")
        self.btn_trim = ttk.Button(kontrol_cerceve, text="Sadece Yüklemeyi Göster", command=self.sadece_yuklemeyi_goster, state="disabled"); self.btn_trim.grid(row=5, column=2, padx=5, pady=5, sticky="ew")
        self.btn_reset_view = ttk.Button(kontrol_cerceve, text="Tüm Veriyi Göster", command=self.tum_veriyi_goster, state="disabled"); self.btn_reset_view.grid(row=5, column=3, padx=5, pady=5, sticky="ew")
        self.lbl_durum = ttk.Label(kontrol_cerceve, text="Hazır."); self.lbl_durum.grid(row=6, column=0, columnspan=4, sticky="w", padx=5)
        self.notebook = ttk.Notebook(main_frame); self.notebook.pack(fill=tk.BOTH, expand=True, pady=10)
        grafik_cerceve = ttk.Frame(self.notebook, padding=10); self.notebook.add(grafik_cerceve, text="Ana Grafik")
        tablo_cerceve = ttk.Frame(self.notebook, padding=10); self.notebook.add(tablo_cerceve, text="Veri Tablosu")
        self.fig, self.ax = plt.subplots(dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=grafik_cerceve); self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(tablo_cerceve, show='headings'); vsb = ttk.Scrollbar(tablo_cerceve, orient="vertical", command=self.tree.yview); hsb = ttk.Scrollbar(tablo_cerceve, orient="horizontal", command=self.tree.xview); self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set); vsb.pack(side='right', fill='y'); hsb.pack(side='bottom', fill='x'); self.tree.pack(side='left', fill='both', expand=True)
        self.annot = self.ax.annotate("", xy=(0, 0), xytext=(20, 20), textcoords="offset points", bbox=dict(boxstyle="round", fc="yellow", alpha=0.7), arrowprops=dict(arrowstyle="->")); self.annot.set_visible(False)
        self.fig.canvas.mpl_connect("motion_notify_event", self.on_hover)

    def id_secildi(self, event=None):
        self.grafigi_temizle()
        selected_id = self.combo_id.get();
        if not selected_id: return
        filepath = self.file_map[selected_id]
        try:
            header_df = pd.read_csv(filepath, sep=r'\s+', header=None, nrows=2, engine='python')
            header_row, unit_row = header_df.iloc[0], header_df.iloc[1]
            sg_columns = [h for h, u in zip(header_row, unit_row) if u == 'μstrain']
            self.original_df = pd.read_csv(filepath, sep=r'\s+', header=0, skiprows=[1], engine='python')
            for col in self.original_df.columns: self.original_df[col] = pd.to_numeric(self.original_df[col], errors='coerce').fillna(0)
            self.calculate_menubutton.config(state="normal")
            self.physical_sg_columns = sg_columns[:]; self.all_sg_columns = sg_columns[:]
            self._tespit_et_hesaplama_gruplarini()
            self.filtrele_sg()
            self._redraw_all_plots()
            self.lbl_durum.config(text=f"{selected_id} yüklendi.")
        except Exception as e:
            messagebox.showerror("Veri Okuma Hatası", f"'{os.path.basename(filepath)}' okunurken hata: {e}")
            self.original_df = None; self.guncelle_tablo(None)

    def on_hover(self, event):
        if event.inaxes != self.ax: return
        vis = self.annot.get_visible()
        lines = self.ax.get_lines()
        if not lines: return
        min_dist = float('inf'); closest_point = None
        for line in lines:
            x_data, y_data = line.get_data()
            if len(x_data) == 0 or event.xdata is None: continue
            distances = np.hypot(x_data - event.xdata, y_data - event.ydata)
            idx = np.argmin(distances); dist = distances[idx]
            if dist < min_dist: min_dist = dist; closest_point = (x_data[idx], y_data[idx], line)
        if closest_point:
            xlim = self.ax.get_xlim(); ylim = self.ax.get_ylim()
            if xlim[1] == xlim[0] or ylim[1] == ylim[0]: return
            tolerance = 0.05 * np.sqrt((xlim[1] - xlim[0])**2 + (ylim[1] - ylim[0])**2)
            if min_dist < tolerance:
                x, y, line = closest_point; self.annot.xy = (x, y)
                self.annot.set_text(f"Load: {x:.2f}\nStrain: {y:.2f}"); self.annot.get_bbox_patch().set_facecolor(line.get_color()); self.annot.set_visible(True)
            else:
                if vis: self.annot.set_visible(False)
        else:
            if vis: self.annot.set_visible(False)
        self.canvas.draw_idle()
        
    def _get_load_column(self):
        if self.original_df is None: return None
        return next((col for col in self.original_df.columns if 'Load_Ratio' in col), None)

    def _tespit_et_hesaplama_gruplarini(self):
        self.shear_rosettes, self.average_pairs = {}, {}
        gecici_gruplar = {}
        pattern = re.compile(r"(\d+)([A-Z])$")
        for sg_name in self.physical_sg_columns:
            if ":" in sg_name:
                base_name, suffix_part = sg_name.split(':', 1)
                match = pattern.match(base_name)
                if match:
                    prefix, letter = match.group(1), match.group(2)
                    if prefix not in gecici_gruplar: gecici_gruplar[prefix] = {"suffix": suffix_part}
                    gecici_gruplar[prefix][letter] = sg_name
        for prefix, gauges in gecici_gruplar.items():
            if 'A' in gauges and 'B' in gauges and 'C' in gauges: self.shear_rosettes[prefix] = gauges
            if 'D' in gauges and 'E' in gauges: self.average_pairs[prefix] = gauges
            
    def on_search_enter(self, event=None):
        if self.combo_sg.get(): self.sg_secildi(); self.btn_plus.focus()
        return "break"

    def filtrele_sg(self, event=None):
        arama_terimi = self.entry_search_sg.get().lower()
        if not self.all_sg_columns: return
        kaba_liste = [sg for sg in self.all_sg_columns if arama_terimi in sg.lower()]
        siralanmis_liste = sorted(kaba_liste, key=lambda sg: (not sg.lower().startswith(arama_terimi), sg.lower()))
        self.combo_sg['values'] = siralanmis_liste
        if siralanmis_liste: self.combo_sg.set(siralanmis_liste[0])
        else: self.combo_sg.set('')

    def guncelle_tablo(self, dataframe):
        self.tree.delete(*self.tree.get_children())
        if dataframe is None or dataframe.empty: self.tree["columns"] = []; return
        self.tree["columns"] = list(dataframe.columns)
        for col in dataframe.columns: self.tree.heading(col, text=col); self.tree.column(col, width=120, anchor='center')
        for index, row in dataframe.iterrows(): self.tree.insert("", tk.END, values=list(row))

    def process_files(self, file_paths):
        self.file_map.clear()
        self.combo_id.set(''); self.combo_id['values'] = []; self.combo_sg.set(''); self.combo_sg['values'] = []
        self.original_df = None; self.prediction_df = None; self.physical_sg_columns = []
        self.grafigi_temizle()
        self.ax.set_title("Veri Yüklenmedi"); self.canvas.draw(); self.guncelle_tablo(None)
        for path in file_paths:
            filename = os.path.basename(path); parts = filename.split('_')
            if len(parts) > 2: self.file_map[parts[1]] = path
        if not self.file_map:
            messagebox.showwarning("Dosya Bulunamadı", "Belirtilen formatta geçerli dosya adı bulunamadı."); return
        sorted_ids = sorted(list(self.file_map.keys()))
        self.combo_id['values'] = sorted_ids
        self.lbl_durum.config(text=f"{len(self.file_map)} adet dosya bulundu. Lütfen bir ID seçin.")
        if len(sorted_ids) == 1: self.combo_id.set(sorted_ids[0]); self.id_secildi()
        
    def dosya_sec(self):
        filepath = filedialog.askopenfilename(title="Bir .dat veri dosyası seçin", filetypes=(("Veri Dosyaları", "*.dat"), ("Tüm Dosyalar", "*.*")))
        if not filepath: return
        self.lbl_kaynak_yolu.config(text=filepath); self.process_files([filepath])

    def klasor_sec(self):
        folder = filedialog.askdirectory(title="İçinde .dat dosyalarının olduğu klasörü seçin")
        if not folder: return
        self.lbl_kaynak_yolu.config(text=folder)
        dat_files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".dat")]
        if not dat_files: messagebox.showwarning("Dosya Bulunamadı", "Seçilen klasörde .dat dosyası bulunamadı."); return
        self.process_files(dat_files)

    def tahmin_verisi_yukle(self):
        if not self.plotted_sgs: messagebox.showwarning("Uyarı", "Lütfen önce en az bir ölçüm verisini grafiğe ekleyin."); return
        path = filedialog.askopenfilename(title="Tahmin Değerlerini İçeren .dat Dosyasını Seçin", filetypes=(("DAT Dosyaları", "*.dat"),("Tüm Dosyalar", "*.*")))
        if not path: return
        try:
            self.prediction_df = pd.read_csv(path, sep=r'\s+', engine='python')
            if not all(col in self.prediction_df.columns for col in ['Load', 'Predicted_Strain']):
                 messagebox.showerror("Sütun Hatası", "'Load' ve 'Predicted_Strain' sütunlarını içermelidir."); self.prediction_df = None; return
            self._redraw_all_plots()
            self.lbl_durum.config(text=f"Tahmin verisi yüklendi ve grafiğe eklendi.")
        except Exception as e:
            messagebox.showerror("Okuma Hatası", f"Tahmin dosyası okunurken hata: {e}"); self.prediction_df = None
            
    def grafik_popup(self):
        if not self.plotted_sgs: messagebox.showwarning("Eksik Bilgi", "Lütfen önce grafiğe en az bir çizgi ekleyin."); return
        pass # Bu fonksiyonun içi, ana mimariyle uyumlu olacak şekilde yeniden yazılabilir. Şimdilik devre dışı.

if __name__ == "__main__":
    root = tk.Tk()
    app = DataAnalyzerApp(root)
    root.mainloop()
