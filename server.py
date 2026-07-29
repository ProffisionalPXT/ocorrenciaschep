import os
import sys
import json
import time
import asyncio
import threading
import socket
from flask import Flask, render_template, request, jsonify, send_from_directory
from bot_engine import CHEPBotEngine

sys.stdout.reconfigure(encoding='utf-8')

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DRIVERS_FILE = os.path.join(BASE_DIR, "drivers.json")
MESSAGES_FILE = os.path.join(BASE_DIR, "messages.json")
DAILY_DELIVERIES_FILE = os.path.join(BASE_DIR, "daily_deliveries.json")
LAST_CHECK_FILE = os.path.join(BASE_DIR, "last_check_time.json")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

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

# Limpa a lista de deliveries monitoradas a cada reinício/push do servidor
# (o usuário adiciona manualmente via interface, não persiste entre restarts)
save_json(DAILY_DELIVERIES_FILE, [])

LOGS_FILE = os.path.join(BASE_DIR, "logs_history.json")

# Carrega logs do disco ao iniciar para não perder com push/reset do host
saved_logs_data = load_json(LOGS_FILE, default={"logs": ["Servidor Web do CHEP Bot iniciado. Acesse pelo PC ou Celular!"], "history": [], "count": 0})
logs_list = saved_logs_data.get("logs", ["Servidor Web do CHEP Bot iniciado."])
monitoring_runs_history = saved_logs_data.get("history", [])
monitor_check_count = saved_logs_data.get("count", 0)
delivery_statuses = {}

def save_logs_disk():
    save_json(LOGS_FILE, {
        "logs": logs_list,
        "history": monitoring_runs_history,
        "count": monitor_check_count
    })

def append_log(msg: str):
    timestamp = time.strftime("[%H:%M:%S] ")
    full_msg = f"{timestamp}{msg}"
    print(full_msg)
    logs_list.append(full_msg)
    if monitoring_runs_history:
        monitoring_runs_history[-1].append(full_msg)
    save_logs_disk()

engine = CHEPBotEngine(log_callback=append_log)
async_loop = asyncio.new_event_loop()

def start_async_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=start_async_loop, args=(async_loop,), daemon=True).start()

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

@app.route("/")
def index():
    drivers = load_json(DRIVERS_FILE)
    messages = load_json(MESSAGES_FILE)
    daily_deliveries = load_json(DAILY_DELIVERIES_FILE, default=[])
    local_ip = get_local_ip()
    return render_template("index.html", drivers=drivers, messages=messages, daily_deliveries=daily_deliveries, local_ip=local_ip, delivery_statuses=delivery_statuses)

@app.route("/screenshots/<filename>")
def serve_screenshot(filename):
    shots_dir = os.path.join(BASE_DIR, "screenshots")
    return send_from_directory(shots_dir, filename)

import urllib.request

LOCAL_RENDER_CACHE_FILE = os.path.join(BASE_DIR, "local_render_state.json")
OFFLINE_QUEUE_FILE = os.path.join(BASE_DIR, "render_offline_queue.json")
RENDER_STORE_FILE = os.path.join(BASE_DIR, "render_state_db.json")

# ==============================================================================
# MÓDULO DE PERSISTÊNCIA E SINCRONIZAÇÃO COM O RENDER
# ==============================================================================
monitoring_lock = threading.Lock()
monitored_deliveries = []
active_profile = "BR__LH_PURM2"
delivery_statuses = {}

def sync_to_render_store():
    """
    Sincroniza imediatamente o estado das deliveries monitoradas com o Render / Cache Local.
    """
    state_payload = {}
    now = time.time()
    with monitoring_lock:
        for d in list(monitored_deliveries):
            st_data = delivery_statuses.get(d, {})
            last_check_ts = st_data.get("updated_at", now)
            created_at_ts = st_data.get("created_at", now)
            next_check_ts = last_check_ts + 1200

            state_payload[d] = {
                "delivery": str(d),
                "status": st_data.get("status", "aguardando_resposta"),
                "resposta_encontrada": st_data.get("resposta_encontrada", False),
                "resposta_confirmada": st_data.get("resposta_confirmada", False),
                "contador": st_data.get("count", 0),
                "ultima_verificacao": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last_check_ts)),
                "ultima_verificacao_ts": last_check_ts,
                "proxima_verificacao": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(next_check_ts)),
                "proxima_verificacao_ts": next_check_ts,
                "monitorando": True,
                "created_at": created_at_ts,
                "last_sent": st_data.get("last_sent", None)
            }

    save_json(LOCAL_RENDER_CACHE_FILE, state_payload)

    def push_remote():
        render_url = os.getenv("RENDER_STORE_URL", "https://ocorrenciaschep.onrender.com/api/render_store")
        try:
            req = urllib.request.Request(
                render_url,
                data=json.dumps(state_payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    pass
        except Exception:
            save_json(OFFLINE_QUEUE_FILE, state_payload)

    threading.Thread(target=push_remote, daemon=True).start()

def restore_from_render_store():
    """
    Ao iniciar o Flask no Host Local: conecta ao Render (ou cache local),
    reconstrói a lista, estados, contadores e horários sem perdas.
    """
    append_log("[RENDER] Conectando ao Render / banco de persistência...")
    render_url = os.getenv("RENDER_STORE_URL", "https://ocorrenciaschep.onrender.com/api/render_store")
    remote_data = None

    try:
        req = urllib.request.Request(render_url, headers={'User-Agent': 'CHEPBotLocal/1.0'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            if resp.status == 200:
                remote_data = json.loads(resp.read().decode('utf-8'))
                append_log("[RENDER] Conexão bem-sucedida! Dados restaurados do Render.")
    except Exception as e:
        append_log(f"[RENDER] Conexão direta indisponível ({e}). Carregando do cache de persistência local...")
        remote_data = load_json(LOCAL_RENDER_CACHE_FILE, default={})

    if not remote_data or not isinstance(remote_data, dict):
        append_log("[RENDER] Nenhuma delivery ativa encontrada na persistência.")
        return

    now = time.time()
    overdue_deliveries = []
    restored_count = 0

    with monitoring_lock:
        monitored_deliveries.clear()
        for deliv, item in remote_data.items():
            if not isinstance(item, dict):
                continue

            created_at = item.get("created_at", now)
            # Limpeza automática diária: descarta registros com mais de 24 horas
            if now - created_at > 86400:
                append_log(f"[RENDER] Delivery #{deliv} expirada (>24h). Removida automaticamente.")
                continue

            if item.get("monitorando", True):
                deliv_str = str(deliv).strip()
                if deliv_str not in monitored_deliveries:
                    monitored_deliveries.append(deliv_str)

                count_val = item.get("contador", 0)
                st_val = item.get("status", "aguardando_resposta")
                resp_enc = item.get("resposta_encontrada", False)
                resp_conf = item.get("resposta_confirmada", False)
                last_sent_val = item.get("last_sent", None)
                last_check_ts = item.get("ultima_verificacao_ts", now)
                next_check_ts = item.get("proxima_verificacao_ts", last_check_ts + 1200)

                delivery_statuses[deliv_str] = {
                    "status": st_val,
                    "resposta_encontrada": resp_enc,
                    "resposta_confirmada": resp_conf,
                    "count": count_val,
                    "last_sent": last_sent_val,
                    "updated_at": last_check_ts,
                    "created_at": created_at
                }
                restored_count += 1

                # Recalcula temporizadores apenas para deliveries com resposta
                if resp_enc:
                    if now >= next_check_ts:
                        append_log(f"[RENDER] Delivery #{deliv_str} com horário vencido. Agendando verificação imediata...")
                        overdue_deliveries.append(deliv_str)
                    else:
                        rem_min = int((next_check_ts - now) // 60)
                        append_log(f"[RENDER] Delivery #{deliv_str} restaurada (Resposta Encontrada, Contador: {count_val}/4, próxima em {rem_min} min).")
                else:
                    append_log(f"[RENDER] Delivery #{deliv_str} restaurada (Aguardando resposta da CHEP - sem timer).")

        save_json(DAILY_DELIVERIES_FILE, monitored_deliveries)

    if restored_count > 0:
        append_log(f"[RENDER] Restauração concluída: {restored_count} delivery(ies) ativa(s) no monitoramento.")

    if overdue_deliveries:
        def run_overdue():
            run_verification_cycle(overdue_deliveries, profile=active_profile, mode="initial")
        threading.Thread(target=run_overdue, daemon=True).start()

saved_time_obj = load_json(LAST_CHECK_FILE, default={})
if isinstance(saved_time_obj, dict) and "last_check_time" in saved_time_obj:
    last_check_time = saved_time_obj["last_check_time"]
else:
    last_check_time = time.time()
    save_json(LAST_CHECK_FILE, {"last_check_time": last_check_time})

def run_verification_cycle(deliveries_to_check, profile="BR__LH_PURM2", mode="manual"):
    """
    Executa o ciclo de verificação no Service Desk para a lista de deliveries fornecida.
    """
    global last_check_time, monitor_check_count, monitoring_runs_history
    if not deliveries_to_check:
        return []

    if mode == "auto":
        append_log("[MONITOR] Executando monitoramento automático...")
        for d in deliveries_to_check:
            append_log(f"[MONITOR] Verificando delivery {d}...")
    elif mode == "initial":
        append_log("[MONITOR] Executando verificação inicial...")
        for d in deliveries_to_check:
            append_log(f"[MONITOR] Verificando delivery {d}...")

    monitor_check_count += 1
    current_run_logs = [f"{time.strftime('[%H:%M:%S] ')}🔍 [Monitor #{monitor_check_count}] Verificando respostas no Service Desk ({profile})..."]
    monitoring_runs_history.append(current_run_logs)
    if len(monitoring_runs_history) > 2:
        monitoring_runs_history.pop(0)

    logs_list.clear()
    for run in monitoring_runs_history:
        logs_list.extend(run)
    save_logs_disk()

    try:
        fut = asyncio.run_coroutine_threadsafe(
            engine.check_pending_carrier_replies(deliveries_to_check, profile_name=profile),
            async_loop
        )
        answered = fut.result(timeout=180) or []
        answered_dict = {item[0]: item for item in answered}

        for deliv in deliveries_to_check:
            st_data = delivery_statuses.get(deliv, {})
            cur_found = st_data.get("resposta_encontrada", False)
            cur_confirmed = st_data.get("resposta_confirmada", False)
            cur_count = st_data.get("count", 0)

            is_chep_reply = False
            last_time = cur_data = st_data.get("last_sent", None)
            if deliv in answered_dict:
                res_item = answered_dict[deliv]
                is_purple = res_item[1]  # True = resposta encontrada no Service Desk
                last_time = res_item[3] if len(res_item) > 3 else None
                if is_purple:
                    is_chep_reply = True

            if is_chep_reply or cur_found:
                # Transição/Manutenção do Estado com Resposta Encontrada
                if not cur_found:
                    new_status = "resposta_encontrada"
                    new_found = True
                    new_confirmed = False
                    new_count = 0
                    append_log(f"🚨 [RESPOSTA ENCONTRADA] Delivery #{deliv} possui nova resposta da CHEP! Cronômetro e contador (0/4) iniciados.")
                else:
                    new_found = True
                    new_confirmed = cur_confirmed
                    new_count = cur_count + 1
                    new_status = "resposta_confirmada" if cur_confirmed else "resposta_encontrada"

                delivery_statuses[deliv] = {
                    "status": new_status,
                    "resposta_encontrada": True,
                    "resposta_confirmada": new_confirmed,
                    "count": new_count,
                    "last_sent": last_time,
                    "updated_at": time.time(),
                    "created_at": st_data.get("created_at", time.time())
                }
            else:
                # Estado 1: Aguardando resposta da CHEP (Sem timer, sem contador)
                delivery_statuses[deliv] = {
                    "status": "aguardando_resposta",
                    "resposta_encontrada": False,
                    "resposta_confirmada": False,
                    "count": 0,
                    "last_sent": None,
                    "updated_at": time.time(),
                    "created_at": st_data.get("created_at", time.time())
                }
                append_log(f"🟣 Delivery #{deliv}: Aguardando resposta da CHEP (sem timer).")

        if mode == "auto":
            last_check_time = time.time()
            save_json(LAST_CHECK_FILE, {"last_check_time": last_check_time})
            append_log("[MONITOR] Monitoramento concluído. Próxima execução em 20 minutos.")

        sync_to_render_store()
        return answered
    except Exception as e:
        append_log(f"⚠️ Erro ao verificar respostas: {e}")
        return []

def add_delivery_to_monitoring(delivery: str, profile: str = "BR__LH_PURM2"):
    """
    Adiciona uma delivery no estado inicial 'aguardando_resposta' (sem timer) e dispara verificação inicial.
    """
    global active_profile
    delivery = str(delivery).strip()
    if not delivery:
        return False

    active_profile = profile
    added = False
    with monitoring_lock:
        if delivery not in monitored_deliveries:
            monitored_deliveries.append(delivery)
            save_json(DAILY_DELIVERIES_FILE, monitored_deliveries)
            delivery_statuses[delivery] = {
                "status": "aguardando_resposta",
                "resposta_encontrada": False,
                "resposta_confirmada": False,
                "count": 0,
                "last_sent": None,
                "updated_at": time.time(),
                "created_at": time.time()
            }
            append_log(f"[MONITOR] Delivery {delivery} adicionada ao monitoramento (Estado: Aguardando resposta).")
            added = True
        else:
            append_log(f"[MONITOR] Delivery {delivery} já está na lista de monitoramento.")

    if added:
        sync_to_render_store()
        def do_initial():
            run_verification_cycle([delivery], profile=profile, mode="initial")
        threading.Thread(target=do_initial, daemon=True).start()

    return added

def remove_delivery_from_monitoring(delivery: str):
    """
    Remove uma delivery da fila de monitoramento.
    """
    delivery = str(delivery).strip()
    with monitoring_lock:
        if delivery in monitored_deliveries:
            monitored_deliveries.remove(delivery)
            save_json(DAILY_DELIVERIES_FILE, monitored_deliveries)
            if delivery in delivery_statuses:
                del delivery_statuses[delivery]
            append_log(f"[MONITOR] Delivery {delivery} removida do monitoramento.")
            sync_to_render_store()
            return True
        return False

# Executa restauração do Render / cache local antes de iniciar o scheduler
restore_from_render_store()

def global_monitoring_scheduler():
    """
    Scheduler em segundo plano no servidor Python.
    A cada 20 minutos (1200 segundos), verifica todas as deliveries da fila de monitoramento.
    """
    global last_check_time
    append_log("[MONITOR] Scheduler global de monitoramento automático iniciado (20 min).")
    while True:
        time.sleep(10)
        now = time.time()
        if now - last_check_time >= 1200:
            with monitoring_lock:
                to_check = list(monitored_deliveries)
            if to_check:
                run_verification_cycle(to_check, profile=active_profile, mode="auto")
            else:
                last_check_time = now
                save_json(LAST_CHECK_FILE, {"last_check_time": last_check_time})

threading.Thread(target=global_monitoring_scheduler, daemon=True).start()

@app.route("/api/confirm_ok", methods=["POST"])
def confirm_ok():
    """
    Registra que o usuário tratou a resposta da delivery no Service Desk.
    Remove o alerta visual de 'Resposta Encontrada' e oculta o botão OK,
    mas MANTÉM a delivery monitorada normalmente com timer e contador ativos.
    """
    data = request.json or {}
    delivery = str(data.get("delivery", "")).strip()
    with monitoring_lock:
        if delivery in delivery_statuses:
            delivery_statuses[delivery]["resposta_confirmada"] = True
            delivery_statuses[delivery]["status"] = "resposta_confirmada"
            append_log(f"✅ Resposta da Delivery #{delivery} confirmada pelo usuário (OK).")
            sync_to_render_store()
            return jsonify({
                "success": True,
                "statuses": delivery_statuses,
                "monitored_deliveries": monitored_deliveries
            })
    return jsonify({"success": False, "error": "Delivery não encontrada"}), 404

@app.route("/api/render_store", methods=["GET", "POST"])
def handle_render_store():
    """
    Endpoint de armazenamento no Render.
    O Render armazena e disponibiliza o JSON de estado sem executar Playwright/automações.
    """
    if request.method == "POST":
        data = request.json or {}
        save_json(RENDER_STORE_FILE, data)
        return jsonify({"success": True, "stored_count": len(data)})
    else:
        stored = load_json(RENDER_STORE_FILE, default={})
        return jsonify(stored)

@app.route("/api/logs")
def get_logs():
    return jsonify({
        "logs": logs_list,
        "statuses": delivery_statuses,
        "monitored_deliveries": monitored_deliveries,
        "last_check_time": last_check_time,
        "server_time": time.time()
    })

@app.route("/api/connect_chrome", methods=["POST"])
def connect_chrome():
    data = request.json or {}
    mode = data.get("mode", "cdp")
    profile = data.get("profile", "BR__LH_PURM2")
    
    fut = asyncio.run_coroutine_threadsafe(engine.get_browser_for_profile(profile), async_loop)
    try:
        fut.result(timeout=25)
        return jsonify({"success": True, "mode": f"Chrome {profile} com 2 Abas Ativas (CMA + Service Desk)"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/execute", methods=["POST"])
def execute_occurrence():
    delivery = request.form.get("delivery", "").strip()
    profile = request.form.get("profile", "BR__LH_PURM2")
    include_driver = request.form.get("include_driver") == "true"
    driver_id = request.form.get("driver_id", "")
    driver_text = request.form.get("driver_text", "").strip()
    
    include_location = request.form.get("include_location") == "true"
    note_type = request.form.get("note_type", "SAP (Not App) LOCALIZAÇÃO DO VEÍCULO")
    location_text = request.form.get("location_text", "").strip()
    
    include_contact = request.form.get("include_contact") == "true"
    priority = request.form.get("priority", "HIGH")
    test_mode = request.form.get("test_mode") == "true"
    coleta_dia = request.form.get("coleta_dia") == "true"

    if not delivery:
        return jsonify({"success": False, "error": "Número da delivery é obrigatório!"}), 400

    attachment_path = None
    if "photo" in request.files:
        file = request.files["photo"]
        if file and file.filename:
            file_path = os.path.join(UPLOADS_DIR, f"{int(time.time())}_{file.filename}")
            file.save(file_path)
            attachment_path = file_path

    # Se a caixa "COLETA DO DIA" estiver marcada, insere na lista de monitoramento contínuo
    if coleta_dia:
        add_delivery_to_monitoring(delivery, profile)

    def run_tasks():
        append_log(f"Perfil: {profile} | Delivery #{delivery}")
        if include_driver and driver_text:
            append_log("[1/3] Ocorrência de DADOS DO MOTORISTA...")
            fut1 = asyncio.run_coroutine_threadsafe(
                engine.create_occurrence(
                    delivery_number=delivery,
                    note_type="SAP (Not App) DADOS MOTORISTA / VEÍCULO",
                    description=driver_text,
                    priority=priority,
                    profile_name=profile,
                    attachment_path=None
                ),
                async_loop
            )
            res1 = fut1.result()
            if not res1:
                append_log(f"❌ Falha no envio da ocorrência do motorista.")

        if include_location and location_text:
            append_log("[2/3] Ocorrência de STATUS / LOCALIZAÇÃO...")
            fut2 = asyncio.run_coroutine_threadsafe(
                engine.create_occurrence(
                    delivery_number=delivery,
                    note_type=note_type,
                    description=location_text,
                    priority=priority,
                    profile_name=profile,
                    attachment_path=attachment_path
                ),
                async_loop
            )
            res2 = fut2.result()
            if not res2:
                append_log(f"❌ Falha no envio da ocorrência de localização.")

        if include_contact:
            append_log("[3/3] Resposta no 2º site (contact.cmaweb.chep.com)...")
            fut3 = asyncio.run_coroutine_threadsafe(
                engine.respond_contact_site(
                    delivery_number=delivery,
                    message_text=location_text or driver_text,
                    profile_name=profile,
                    attachment_path=attachment_path
                ),
                async_loop
            )
            fut3.result()

        append_log(f"🚀 Processo concluído com sucesso para a Delivery #{delivery}!")

    threading.Thread(target=run_tasks, daemon=True).start()
    return jsonify({"success": True, "message": "Preenchimento iniciado em segundo plano!"})

@app.route("/api/approval_status", methods=["GET"])
def approval_status():
    if engine.approval_state and engine.approval_state.get("event") is not None:
        return jsonify({
            "pending": True,
            "image_url": engine.approval_state.get("image_url"),
            "delivery": engine.approval_state.get("delivery")
        })
    return jsonify({"pending": False})

@app.route("/api/resolve_approval", methods=["POST"])
def resolve_approval():
    data = request.json or {}
    action = data.get("action")
    if engine.approval_state and engine.approval_state.get("event"):
        engine.approval_state["action"] = action
        asyncio.run_coroutine_threadsafe(
            engine.set_approval_event(),
            async_loop
        )
        return jsonify({"success": True, "message": f"Ação '{action}' registrada com sucesso."})
    return jsonify({"success": False, "error": "Nenhuma aprovação pendente."}), 400

@app.route("/api/check_replies", methods=["POST"])
def check_replies():
    data = request.json or {}
    profile = data.get("profile", "BR__LH_PURM2")
    deliveries_to_check = data.get("deliveries")
    add_to_monitor = data.get("add_to_monitor", False)

    if add_to_monitor and deliveries_to_check:
        for d in deliveries_to_check:
            add_delivery_to_monitoring(d, profile)
        return jsonify({
            "success": True,
            "monitored_deliveries": monitored_deliveries,
            "statuses": delivery_statuses,
            "last_check_time": last_check_time,
            "server_time": time.time()
        })

    if not deliveries_to_check:
        deliveries_to_check = list(monitored_deliveries)

    if not deliveries_to_check:
        return jsonify({
            "success": True,
            "message": "Nenhuma delivery para verificar.",
            "answered_deliveries": [],
            "statuses": delivery_statuses,
            "last_check_time": last_check_time,
            "server_time": time.time()
        })

    # Verificação pontual / manual
    answered = run_verification_cycle(deliveries_to_check, profile=profile, mode="manual")

    return jsonify({
        "success": True,
        "answered_deliveries": [item[0] for item in answered if item[1]],
        "statuses": delivery_statuses,
        "last_check_time": last_check_time,
        "server_time": time.time()
    })

@app.route("/api/remove_monitoring", methods=["POST"])
def remove_monitoring():
    data = request.json or {}
    delivery = data.get("delivery", "").strip()
    removed = remove_delivery_from_monitoring(delivery)
    return jsonify({
        "success": removed,
        "monitored_deliveries": monitored_deliveries,
        "statuses": delivery_statuses
    })

@app.route("/api/save_daily_deliveries", methods=["POST"])
def save_daily_deliveries():
    data = request.json or {}
    deliveries = data.get("deliveries", [])
    clean_delivs = [str(d).strip() for d in deliveries if str(d).strip()]
    with monitoring_lock:
        monitored_deliveries.clear()
        monitored_deliveries.extend(clean_delivs)
        save_json(DAILY_DELIVERIES_FILE, monitored_deliveries)
    return jsonify({"success": True, "deliveries": monitored_deliveries})

@app.route("/api/drivers", methods=["GET", "POST", "DELETE"])
def handle_drivers():
    drivers = load_json(DRIVERS_FILE)
    if request.method == "GET":
        return jsonify(drivers)
    elif request.method == "POST":
        new_driver = request.json
        drivers.append(new_driver)
        save_json(DRIVERS_FILE, drivers)
        return jsonify({"success": True, "drivers": drivers})
    elif request.method == "DELETE":
        driver_id = request.args.get("id")
        drivers = [d for d in drivers if str(d.get("id")) != str(driver_id)]
        save_json(DRIVERS_FILE, drivers)
        return jsonify({"success": True, "drivers": drivers})

@app.route("/api/messages", methods=["GET", "POST", "DELETE"])
def handle_messages():
    messages = load_json(MESSAGES_FILE)
    if request.method == "GET":
        return jsonify(messages)
    elif request.method == "POST":
        new_msg = request.json
        messages.append(new_msg)
        save_json(MESSAGES_FILE, messages)
        return jsonify({"success": True, "messages": messages})
    elif request.method == "DELETE":
        msg_id = request.args.get("id")
        messages = [m for m in messages if str(m.get("id")) != str(msg_id)]
        save_json(MESSAGES_FILE, messages)
        return jsonify({"success": True, "messages": messages})

if __name__ == "__main__":
    local_ip = get_local_ip()
    print("=" * 65)
    print("CHEP BOT WEB SERVER INICIADO!")
    print(f"Acese pelo PC:      http://localhost:5000")
    print(f"Acese pelo Celular: http://{local_ip}:5000")
    print("=" * 65)
    app.run(host="0.0.0.0", port=5000, debug=False)
