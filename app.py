import sys
import os
import re
import json
import asyncio
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk

from bot_engine import CHEPBotEngine

# Configurações globais do tema CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DRIVERS_FILE = os.path.join(BASE_DIR, "drivers.json")
MESSAGES_FILE = os.path.join(BASE_DIR, "messages.json")
DAILY_DELIVERIES_FILE = os.path.join(BASE_DIR, "daily_deliveries.json")

def load_json(filepath, default=[]):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Erro ao salvar json: {e}")

class CHEPBotApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("CHEP Bot - Automação & Modo Teste (Simulação Segura)")
        self.geometry("1120x970")
        self.minsize(960, 820)

        # Dados carregados
        self.drivers = load_json(DRIVERS_FILE)
        self.preset_messages = load_json(MESSAGES_FILE)
        self.daily_deliveries = load_json(DAILY_DELIVERIES_FILE, default=[])
        
        self.engine = CHEPBotEngine(log_callback=self.append_log)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.run_async_loop, daemon=True)
        self.thread.start()

        self.attached_file_path = None
        self.is_criacao_linha_mode = False
        self.monitor_active = False

        self.setup_ui()

    def run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def append_log(self, text: str):
        self.after(0, self._append_log_sync, text)

    def _append_log_sync(self, text: str):
        self.log_textbox.configure(state="normal")
        self.log_textbox.insert("end", text + "\n")
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def setup_ui(self):
        # Header / Conexão
        header_frame = ctk.CTkFrame(self, corner_radius=10)
        header_frame.pack(fill="x", padx=15, pady=10)

        title_lbl = ctk.CTkLabel(
            header_frame, 
            text="🛡️ CHEP Bot - Modo Teste Ativado (Segurança)", 
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color="#f59e0b"
        )
        title_lbl.pack(side="left", padx=15, pady=10)

        self.status_indicator = ctk.CTkLabel(
            header_frame, 
            text="🔴 Não Conectado", 
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#ff5555"
        )
        self.status_indicator.pack(side="right", padx=15, pady=10)

        btn_cdp = ctk.CTkButton(
            header_frame, 
            text="🔗 Conectar Chrome Aberto (Porta 9222)", 
            command=self.connect_chrome_cdp,
            fg_color="#2b5c8f",
            hover_color="#1d3f63"
        )
        btn_cdp.pack(side="right", padx=5, pady=10)

        btn_new_browser = ctk.CTkButton(
            header_frame, 
            text="🚀 Abrir Novo Chrome", 
            command=self.launch_new_chrome,
            fg_color="#28a745",
            hover_color="#1e7e34"
        )
        btn_new_browser.pack(side="right", padx=5, pady=10)

        # Main Layout: Left Panel (Inputs) & Right Panel (Preview/Logs & Monitor)
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=15, pady=5)

        # ---------------- LEFT PANEL (FORM) ----------------
        left_frame = ctk.CTkScrollableFrame(main_container, width=550, label_text="Dados da Ocorrência")
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # 0. Perfil Selection (Perfil 2 / Perfil 3)
        prof_frame = ctk.CTkFrame(left_frame, fg_color="#0f172a", corner_radius=8)
        prof_frame.pack(fill="x", padx=10, pady=(10, 10))

        prof_title = ctk.CTkLabel(prof_frame, text="👤 Seleção de Perfil CHEP:", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8")
        prof_title.pack(side="left", padx=10, pady=8)

        self.profile_combo = ctk.CTkComboBox(
            prof_frame, 
            values=["BR__LH_PURM2 (Perfil 2)", "BR__LH_PURM3 (Perfil 3)"], 
            width=220,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.profile_combo.set("BR__LH_PURM2 (Perfil 2)")
        self.profile_combo.pack(side="right", padx=10, pady=8)

        # 1. Delivery Number
        deliv_lbl = ctk.CTkLabel(left_frame, text="1. Número de Delivery / Carga *", font=ctk.CTkFont(size=14, weight="bold"))
        deliv_lbl.pack(anchor="w", padx=10, pady=(5, 2))
        
        self.deliv_entry = ctk.CTkEntry(left_frame, placeholder_text="Ex: 3788216684", height=38, font=ctk.CTkFont(size=15))
        self.deliv_entry.pack(fill="x", padx=10, pady=(0, 15))

        # 2. Driver Selection (Dados Motorista)
        self.chk_driver_var = ctk.BooleanVar(value=True)
        chk_driver = ctk.CTkCheckBox(
            left_frame, 
            text="2. Ocorrência de Dados do Motorista",
            variable=self.chk_driver_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.on_driver_toggle
        )
        chk_driver.pack(anchor="w", padx=10, pady=(5, 5))

        driver_options = ["-- Sem Motorista (Em Branco) --"] + [
            f"{d['name']} (CPF: {d['cpf']})" for d in self.drivers
        ]
        
        self.driver_combo = ctk.CTkComboBox(
            left_frame, 
            values=driver_options, 
            height=35, 
            command=self.on_driver_selected
        )
        self.driver_combo.set(driver_options[0])
        self.driver_combo.pack(fill="x", padx=10, pady=(0, 8))

        # Preview do Texto do Motorista
        self.driver_text_preview = ctk.CTkTextbox(left_frame, height=80, font=ctk.CTkFont(size=12))
        self.driver_text_preview.pack(fill="x", padx=10, pady=(0, 15))
        self.update_driver_text_preview()

        # 3. Location / Status Message Selection
        self.chk_location_var = ctk.BooleanVar(value=True)
        chk_location = ctk.CTkCheckBox(
            left_frame, 
            text="3. Ocorrência de Localização / Status / Coletado / Criação de Linha",
            variable=self.chk_location_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.on_location_toggle
        )
        chk_location.pack(anchor="w", padx=10, pady=(5, 5))

        msg_options = ["-- Selecione uma Mensagem Pronta --"] + [
            f"{m['title']}" for m in self.preset_messages
        ] + ["-- Texto Livre Personalizado --"]

        self.msg_combo = ctk.CTkComboBox(
            left_frame, 
            values=msg_options, 
            height=35, 
            command=self.on_message_selected
        )
        self.msg_combo.set(msg_options[1]) # Padrão: COLETADO
        self.msg_combo.pack(fill="x", padx=10, pady=(0, 5))

        note_type_lbl = ctk.CTkLabel(left_frame, text="Tipo de Nota no CHEP:", font=ctk.CTkFont(size=11, weight="bold"))
        note_type_lbl.pack(anchor="w", padx=10, pady=(2, 0))

        self.note_type_entry = ctk.CTkEntry(left_frame, height=30, font=ctk.CTkFont(size=12))
        self.note_type_entry.pack(fill="x", padx=10, pady=(0, 8))

        # Painel Especial para CRIAÇÃO DE LINHA
        self.criacao_linha_frame = ctk.CTkFrame(left_frame, fg_color="#1e293b", corner_radius=8)
        
        cl_title = ctk.CTkLabel(self.criacao_linha_frame, text="⚙️ Campos da Criação de Linha (Edição Rápida):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8")
        cl_title.pack(anchor="w", padx=10, pady=(8, 4))

        fields_grid = ctk.CTkFrame(self.criacao_linha_frame, fg_color="transparent")
        fields_grid.pack(fill="x", padx=5, pady=(0, 8))

        ctk.CTkLabel(fields_grid, text="Nº Nota Fiscal:", font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=5, pady=2, sticky="w")
        self.entry_nf = ctk.CTkEntry(fields_grid, width=120, height=28)
        self.entry_nf.grid(row=0, column=1, padx=5, pady=2)
        self.entry_nf.insert(0, "2763971")
        self.entry_nf.bind("<KeyRelease>", lambda e: self.update_criacao_linha_preview())

        ctk.CTkLabel(fields_grid, text="Qtd Pallets:", font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=5, pady=2, sticky="w")
        self.entry_pallets = ctk.CTkEntry(fields_grid, width=80, height=28)
        self.entry_pallets.grid(row=0, column=3, padx=5, pady=2)
        self.entry_pallets.insert(0, "408")
        self.entry_pallets.bind("<KeyRelease>", lambda e: self.update_criacao_linha_preview())

        ctk.CTkLabel(fields_grid, text="CNPJ:", font=ctk.CTkFont(size=11)).grid(row=1, column=0, padx=5, pady=2, sticky="w")
        self.entry_cnpj = ctk.CTkEntry(fields_grid, width=200, height=28)
        self.entry_cnpj.grid(row=1, column=1, columnspan=3, padx=5, pady=2, sticky="w")
        self.entry_cnpj.insert(0, "06.189.213/0001-90")
        self.entry_cnpj.bind("<KeyRelease>", lambda e: self.update_criacao_linha_preview())

        self.location_text_box = ctk.CTkTextbox(left_frame, height=90, font=ctk.CTkFont(size=12))
        self.location_text_box.pack(fill="x", padx=10, pady=(0, 10))
        # self.on_message_selected(msg_options[1])  # moved later

        # 4. Checkbox para 2º Sistema (Contact CHEP)
        self.chk_contact_var = ctk.BooleanVar(value=False)
        chk_contact = ctk.CTkCheckBox(
            left_frame,
            text="🌐 Responder no 2º site (contact.cmaweb.chep.com)",
            variable=self.chk_contact_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#38bdf8"
        )
        chk_contact.pack(anchor="w", padx=10, pady=(0, 5))

        lbl_status_note = ctk.CTkLabel(
            left_frame, 
            text="ℹ️ Envia se status 'Pending internal reply' (Amarelo). Se 'Pending carrier reply' (Roxo), o robô emitirá um alerta.", 
            font=ctk.CTkFont(size=10, slant="italic"), 
            text_color="#94a3b8"
        )
        lbl_status_note.pack(anchor="w", padx=10, pady=(0, 15))

        # 5. Anexos e Prioridade
        opt_frame = ctk.CTkFrame(left_frame, fg_color="transparent")
        opt_frame.pack(fill="x", padx=10, pady=(0, 5))

        prio_lbl = ctk.CTkLabel(opt_frame, text="Prioridade:", font=ctk.CTkFont(size=12, weight="bold"))
        prio_lbl.pack(side="left", padx=(0, 5))

        self.prio_combo = ctk.CTkComboBox(opt_frame, values=["HIGH", "NOT_DEFINE", "NORMAL"], width=120)
        self.prio_combo.set("HIGH")
        self.prio_combo.pack(side="left", padx=(0, 15))

        btn_attach = ctk.CTkButton(
            opt_frame, 
            text="📎 Anexar Foto NF/Comprovante", 
            command=self.select_attachment,
            fg_color="#3b82f6",
            hover_color="#2563eb"
        )
        btn_attach.pack(side="left")

        self.lbl_attachment = ctk.CTkLabel(left_frame, text="Nenhum arquivo anexado", font=ctk.CTkFont(size=11, slant="italic"), text_color="#aaaaaa")
        self.lbl_attachment.pack(anchor="w", padx=10, pady=(0, 15))

        # 6. MODO TESTE (TRAVA DE SEGURANÇA: ATIVADO POR PADRÃO value=True!)
        self.chk_test_mode_var = ctk.BooleanVar(value=True)
        chk_test_mode = ctk.CTkCheckBox(
            left_frame,
            text="🧪 MODO TESTE ATIVADO (Simulação: Preenche tudo, tira print e NÃO salva)",
            variable=self.chk_test_mode_var,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f59e0b"
        )
        chk_test_mode.pack(anchor="w", padx=10, pady=(0, 10))

        # Execute Button
        btn_execute = ctk.CTkButton(
            left_frame, 
            text="🧪 SIMULAR E TESTAR (NÃO SALVA)", 
            font=ctk.CTkFont(size=16, weight="bold"),
            height=48,
            fg_color="#d97706",
            hover_color="#b45309",
            command=self.run_automation
        )
        self.btn_execute = btn_execute
        self.btn_execute.pack(fill="x", padx=10, pady=(5, 15))

        self.chk_test_mode_var.trace_add("write", self.on_test_mode_change)

        # ---------------- RIGHT PANEL (LOGS & MONITOR) ----------------
        right_frame = ctk.CTkFrame(main_container)
        right_frame.pack(side="right", fill="both", expand=True)

        daily_box = ctk.CTkFrame(right_frame, fg_color="#1e1b4b", corner_radius=8)
        daily_box.pack(fill="x", padx=10, pady=(10, 5))

        d_header = ctk.CTkFrame(daily_box, fg_color="transparent")
        d_header.pack(fill="x", padx=10, pady=(6, 2))

        d_title = ctk.CTkLabel(d_header, text="📋 Deliveries do Dia (Monitor 20 min):", font=ctk.CTkFont(size=12, weight="bold"), text_color="#a78bfa")
        d_title.pack(side="left")

        self.chk_auto_monitor_var = ctk.BooleanVar(value=False)
        chk_auto_mon = ctk.CTkCheckBox(
            d_header,
            text="🔔 Monitorar a cada 20 min",
            variable=self.chk_auto_monitor_var,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#c084fc",
            command=self.toggle_auto_monitor
        )
        chk_auto_mon.pack(side="right")

        self.daily_text = ctk.CTkTextbox(daily_box, height=75, font=ctk.CTkFont(size=11))
        self.daily_text.pack(fill="x", padx=10, pady=(0, 6))
        self.daily_text.insert("1.0", "\n".join(self.daily_deliveries))

        btn_check_now = ctk.CTkButton(
            daily_box, 
            text="🔍 Verificar Respostas (Roxo) Agora", 
            command=self.check_replies_now,
            fg_color="#8b5cf6",
            hover_color="#7c3aed",
            height=28
        )
        btn_check_now.pack(anchor="e", padx=10, pady=(0, 6))

        # LOGS TEXTBOX
        log_lbl = ctk.CTkLabel(right_frame, text="📋 Histórico de Execução (Logs)", font=ctk.CTkFont(size=14, weight="bold"))
        log_lbl.pack(anchor="w", padx=15, pady=(5, 5))

        self.log_textbox = ctk.CTkTextbox(right_frame, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_textbox.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.log_textbox.configure(state="disabled")

        self.append_log("🛡️ MODO TESTE (SIMULAÇÃO) ATIVADO POR PADRÃO PARA SUA SEGURANÇA.")
        self.append_log("Nenhuma ocorrência será salva a menos que você desmarque a caixa de Modo Teste.")

    def on_test_mode_change(self, *args):
        if self.chk_test_mode_var.get():
            self.btn_execute.configure(
                text="🧪 SIMULAR E TESTAR (NÃO SALVA)",
                fg_color="#d97706",
                hover_color="#b45309"
            )
        else:
            self.btn_execute.configure(
                text="⚡ EXECUTAR E CRIAR OCORRÊNCIA(S) REAL",
                fg_color="#16a34a",
                hover_color="#15803d"
            )

    def on_driver_toggle(self):
        state = "normal" if self.chk_driver_var.get() else "disabled"
        self.driver_combo.configure(state=state)
        self.driver_text_preview.configure(state=state)

    def on_location_toggle(self):
        state = "normal" if self.chk_location_var.get() else "disabled"
        self.msg_combo.configure(state=state)
        self.note_type_entry.configure(state=state)
        self.location_text_box.configure(state=state)

    def on_driver_selected(self, choice):
        self.update_driver_text_preview()

    def update_driver_text_preview(self):
        choice = self.driver_combo.get()
        text = ""
        if "-- Sem Motorista" not in choice:
            for d in self.drivers:
                if d['name'] in choice:
                    text = f"Segue abaixo dados do veiculo e motorista que irá realizar a coleta.\n\nNOME: {d['name']}\nCPF: {d['cpf']}\nPLACA: {d['placa']}"
                    break
        else:
            text = "(Nenhum motorista selecionado)"

        self.driver_text_preview.delete("1.0", "end")
        self.driver_text_preview.insert("1.0", text)

    def on_message_selected(self, choice):
        selected_msg = None
        for m in self.preset_messages:
            if m['title'] in choice:
                selected_msg = m
                break

        if selected_msg and "deslocamento" in selected_msg['id']:
            self.chk_contact_var.set(True)
        else:
            self.chk_contact_var.set(False)

        if selected_msg and selected_msg.get('is_criacao_linha'):
            self.is_criacao_linha_mode = True
            self.criacao_linha_frame.pack(fill="x", padx=10, pady=(0, 10))
            self.note_type_entry.delete(0, "end")
            self.note_type_entry.insert(0, selected_msg['note_type'])
            self.update_criacao_linha_preview()
        else:
            self.is_criacao_linha_mode = False
            self.criacao_linha_frame.pack_forget()
            
            if selected_msg:
                self.note_type_entry.delete(0, "end")
                self.note_type_entry.insert(0, selected_msg['note_type'])
                self.location_text_box.delete("1.0", "end")
                self.location_text_box.insert("1.0", selected_msg['text'])
            elif choice == "-- Texto Livre Personalizado --":
                self.note_type_entry.delete(0, "end")
                self.note_type_entry.insert(0, "SAP (Not App) LOCALIZAÇÃO DO VEÍCULO")
                self.location_text_box.delete("1.0", "end")
                self.location_text_box.insert("1.0", "")

    def update_criacao_linha_preview(self):
        if not self.is_criacao_linha_mode:
            return
        
        nf = self.entry_nf.get().strip() or "2763971"
        pallets = self.entry_pallets.get().strip() or "408"
        cnpj = self.entry_cnpj.get().strip() or "06.189.213/0001-90"

        text = f"Favor Alterar Ordem, pois a Nota Fiscal {nf}. {pallets} Pallets saiu com o CNPJ: {cnpj}"
        
        self.location_text_box.delete("1.0", "end")
        self.location_text_box.insert("1.0", text)

    def select_attachment(self):
        filename = filedialog.askopenfilename(
            title="Selecionar Imagem / Documento",
            filetypes=[("Arquivos de Imagem / PDF", "*.jpg *.jpeg *.png *.pdf"), ("Todos os Arquivos", "*.*")]
        )
        if filename:
            self.attached_file_path = filename
            self.lbl_attachment.configure(text=f"📎 Anetado: {os.path.basename(filename)}", text_color="#38bdf8")
        else:
            self.attached_file_path = None
            self.lbl_attachment.configure(text="Nenhum arquivo anexado", text_color="#aaaaaa")

    def connect_chrome_cdp(self):
        asyncio.run_coroutine_threadsafe(self._async_connect_cdp(), self.loop)

    async def _async_connect_cdp(self):
        success = await self.engine.connect_cdp()
        if success:
            self.status_indicator.configure(text="🟢 Chrome Conectado (CDP)", text_color="#22c55e")
        else:
            self.status_indicator.configure(text="🔴 Falha Conexão CDP", text_color="#ef4444")
            messagebox.showwarning(
                "Aviso de Conexão", 
                "Não foi possível conectar ao Chrome aberto na porta 9222.\n\n"
                "Dica: Abra o Chrome via atalho com '--remote-debugging-port=9222' ou clique em 'Abrir Novo Chrome'."
            )

    def launch_new_chrome(self):
        asyncio.run_coroutine_threadsafe(self._async_launch_chrome(), self.loop)

    async def _async_launch_chrome(self):
        success = await self.engine.launch_new_browser(headless=False)
        if success:
            self.status_indicator.configure(text="🟢 Chrome Automação Ativo", text_color="#22c55e")
        else:
            self.status_indicator.configure(text="🔴 Erro ao abrir Chrome", text_color="#ef4444")

    def add_delivery_to_daily_list(self, delivery: str):
        if delivery and delivery not in self.daily_deliveries:
            self.daily_deliveries.append(delivery)
            save_json(DAILY_DELIVERIES_FILE, self.daily_deliveries)
            self.daily_text.delete("1.0", "end")
            self.daily_text.insert("1.0", "\n".join(self.daily_deliveries))

    def get_current_daily_deliveries(self):
        raw_text = self.daily_text.get("1.0", "end-1c")
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        return lines

    def toggle_auto_monitor(self):
        if self.chk_auto_monitor_var.get():
            self.monitor_active = True
            self.append_log("🔔 Monitoramento automático de respostas CHEP ATIVADO (Intervalo: 20 min).")
            self.schedule_next_monitor(1000)
        else:
            self.monitor_active = False
            self.append_log("🔕 Monitoramento automático DESATIVADO.")

    def schedule_next_monitor(self, delay_ms: int = 1200000):
        if self.monitor_active:
            self.after(delay_ms, self.trigger_monitor_check)

    def trigger_monitor_check(self):
        if not self.monitor_active:
            return
        self.check_replies_now()
        self.schedule_next_monitor(1200000)

    def check_replies_now(self):
        deliveries = self.get_current_daily_deliveries()
        if not deliveries:
            self.append_log("⚠️ Nenhuma delivery cadastrada na lista de Deliveries do Dia para verificar.")
            return

        raw_profile = self.profile_combo.get()
        profile_code = "BR__LH_PURM2" if "PURM2" in raw_profile else "BR__LH_PURM3"

        asyncio.run_coroutine_threadsafe(self._async_check_replies(deliveries, profile_code), self.loop)

    async def _async_check_replies(self, deliveries: list, profile_code: str):
        answered = await self.engine.check_pending_carrier_replies(deliveries, profile_code)
        if answered:
            ans_str = ", ".join([f"#{d}" for d in answered])
            self.after(0, lambda: messagebox.showwarning(
                "🚨 RESPOSTA CHEP DETECTADA!",
                f"As seguintes deliveries foram RESPONDIDAS pela CHEP! (Status Roxo):\n\n"
                f"{ans_str}\n\n"
                "Acesse o Contact CHEP para visualizar a resposta!"
            ))

    def run_automation(self):
        delivery = self.deliv_entry.get().strip()
        if not delivery:
            messagebox.showwarning("Campo Obrigatório", "Por favor, digite o número da Delivery!")
            return

        if not self.chk_driver_var.get() and not self.chk_location_var.get():
            messagebox.showwarning("Seleção Inválida", "Marque pelo menos uma ocorrência para criar (Dados ou Localização).")
            return

        self.add_delivery_to_daily_list(delivery)

        asyncio.run_coroutine_threadsafe(self._async_run_automation(delivery), self.loop)

    async def _async_run_automation(self, delivery: str):
        priority = self.prio_combo.get()
        is_test_mode = self.chk_test_mode_var.get()
        
        raw_profile = self.profile_combo.get()
        profile_code = "BR__LH_PURM2" if "PURM2" in raw_profile else "BR__LH_PURM3"

        self.append_log(f"\n👤 Perfil ativo selecionado: {profile_code}")
        if is_test_mode:
            self.append_log("🛡️ [MODO TESTE ATIVADO] TRAVA DE SEGURANÇA: Formulário será preenchido e print tirado, NADA SERÁ SALVO OU ENVIADO!")

        # 1. Ocorrência de Dados do Motorista
        if self.chk_driver_var.get():
            driver_choice = self.driver_combo.get()
            driver_text = self.driver_text_preview.get("1.0", "end-1c").strip()

            if "-- Sem Motorista" not in driver_choice and driver_text:
                self.append_log(f"\n🚀 === [1/3] Ocorrência de DADOS DO MOTORISTA ===")
                await self.engine.create_occurrence(
                    delivery_number=delivery,
                    note_type="SAP (Not App) DADOS MOTORISTA / VEÍCULO",
                    description=driver_text,
                    priority=priority,
                    profile_name=profile_code,
                    attachment_path=None,
                    test_mode=is_test_mode
                )
                await asyncio.sleep(2)

        # 2. Ocorrência de Localização / Status / Coletado / Criação de Linha
        location_text = ""
        if self.chk_location_var.get():
            note_type = self.note_type_entry.get().strip() or "SAP (Not App) LOCALIZAÇÃO DO VEÍCULO"
            location_text = self.location_text_box.get("1.0", "end-1c").strip()

            if location_text:
                self.append_log(f"\n🚀 === [2/3] Ocorrência de STATUS / COLETADO / LINHA no CMA Web ===")
                await self.engine.create_occurrence(
                    delivery_number=delivery,
                    note_type=note_type,
                    description=location_text,
                    priority=priority,
                    profile_name=profile_code,
                    attachment_path=self.attached_file_path,
                    test_mode=is_test_mode
                )
                await asyncio.sleep(2)

        # 3. Ocorrência / Resposta no 2º Site (contact.cmaweb.chep.com)
        if self.chk_contact_var.get():
            self.append_log(f"\n🌐 === [3/3] Abrindo 2º Site (contact.cmaweb.chep.com) ===")
            reply_msg = location_text or "Por falta de retorno e exceder o limite de 2H de espera e não ter sucesso na coleta estamos retirando o veiculo do local.\n\nFavor, autorizar deslocamento vazio."
            
            status_result = await self.engine.create_contact_chep_response(
                delivery_number=delivery,
                reply_message=reply_msg,
                profile_name=profile_code,
                test_mode=is_test_mode
            )

            if status_result == "PENDING_CARRIER_REPLY":
                self.after(0, lambda: messagebox.showwarning(
                    "⚠️ Ocorrência já Respondida",
                    f"A Delivery #{delivery} no Contact CHEP possui o status 'Pending carrier reply' (ROXO).\n\n"
                    "O robô NÃO enviou a resposta automática para evitar duplicidade. Por favor, verifique manualmente no navegador!"
                ))

        self.append_log("\n✨ Processo de automação/simulação concluído!")

if __name__ == "__main__":
    app = CHEPBotApp()
    app.mainloop()
