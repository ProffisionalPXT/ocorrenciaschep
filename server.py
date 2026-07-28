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

logs_list = ["Servidor Web do CHEP Bot iniciado. Acesse pelo PC ou Celular!"]
delivery_statuses = {}

def append_log(msg: str):
    timestamp = time.strftime("[%H:%M:%S] ")
    full_msg = f"{timestamp}{msg}"
    print(full_msg)
    logs_list.append(full_msg)
    if len(logs_list) > 40:
        logs_list.pop(0)

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

@app.route("/api/logs")
def get_logs():
    return jsonify({"logs": logs_list, "statuses": delivery_statuses})

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

    daily_deliveries = load_json(DAILY_DELIVERIES_FILE, default=[])
    if coleta_dia and delivery not in daily_deliveries:
        daily_deliveries.append(delivery)
        save_json(DAILY_DELIVERIES_FILE, daily_deliveries)
        delivery_statuses[delivery] = "yellow"
        append_log(f"🔔 Delivery #{delivery} adicionada ao monitoramento 'COLETA DO DIA' (a cada 20 min)!")

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

        # Se for COLETA DO DIA, verifica imediatamente no Service Desk se já possui resposta e atualiza o painel
        if coleta_dia:
            append_log(f"🔍 [Coleta do Dia] Verificando imediatamente se a Delivery #{delivery} possui resposta no Service Desk...")
            try:
                fut_check = asyncio.run_coroutine_threadsafe(
                    engine.check_pending_carrier_replies([delivery], profile_name=profile),
                    async_loop
                )
                fut_check.result()
            except Exception as e_chk:
                append_log(f"⚠️ Aviso na verificação imediata: {e_chk}")

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
    if not deliveries_to_check:
        deliveries_to_check = load_json(DAILY_DELIVERIES_FILE, default=[])
    
    if not deliveries_to_check:
        return jsonify({"success": True, "message": "Nenhuma delivery para verificar.", "answered_deliveries": [], "statuses": delivery_statuses})

    append_log(f"🔍 [Monitor] Verificando respostas pendentes no Service Desk ({profile})...")
    try:
        fut = asyncio.run_coroutine_threadsafe(
            engine.check_pending_carrier_replies(deliveries_to_check, profile_name=profile),
            async_loop
        )
        answered = fut.result(timeout=120)
        for deliv in answered:
            delivery_statuses[deliv] = "purple"
            append_log(f"🚨 Delivery #{deliv} atualizada para ROXO!")
        return jsonify({"success": True, "answered_deliveries": answered, "statuses": delivery_statuses})
    except Exception as e:
        append_log(f"⚠️ Erro ao verificar respostas: {e}")
        return jsonify({"success": False, "error": str(e), "answered_deliveries": [], "statuses": delivery_statuses})

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
