from flask import Flask, render_template_string, request, send_file, redirect, url_for
import io
import os
import math
import json
import html
import socket
import sqlite3
import traceback
import urllib.request
import urllib.error
from datetime import datetime
from fpdf import FPDF

app = Flask(__name__)

# --- 1. CONFIGURAÇÃO DO SUPABASE (NUVEM) ---
PROJECT_REF = "zkhjvkajtjhqlxkzxpx"
SUPABASE_KEY_RAW = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpraGp2a2FqdGp0aHFseGt6eHB4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ0OTk0MjAsImV4cCI6MjExMDA3NTQyMH0.i3K8SXNNPHamqLobcdK-yJ1YyGgS7-qqRpfjLnJPqE4"

SUPABASE_URL = f"https://{PROJECT_REF}.supabase.co"
SUPABASE_KEY = "".join(c for c in SUPABASE_KEY_RAW if 32 < ord(c) < 127).strip()

# --- 2. CONFIGURAÇÃO DE ALERTA TELEGRAM ---
TELEGRAM_BOT_TOKEN = "9209744162:AAE-Yg8v1EBtifwf1LnF6gQSLf8kDbtkhuQ".strip()
TELEGRAM_CHAT_ID = "7635246193".strip()

# --- 3. DISPARO AUTOMÁTICO WHATSAPP (OPCIONAL - EVOLUTION API / Z-API) ---
# Preencha quando quiser que o robô envie o link do laudo direto no WhatsApp do lead
WHATSAPP_API_URL = "".strip()      # Ex: https://sua-api.com/message/sendText/doutorcaixa
WHATSAPP_API_TOKEN = "".strip()    # Sua API Key da instância
WHATSAPP_SUPORTE = "5581979091165"

# --- 4. BANCO LOCAL SQLITE (GARANTIA DE PERSISTÊNCIA E FALLBACK INSTANTÂNEO) ---
DB_LOCAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "doutor_caixa.db")


def init_sqlite():
    conn = sqlite3.connect(DB_LOCAL_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS clientes_doutor_caixa (
            cnpj TEXT PRIMARY KEY,
            nome TEXT,
            ativo INTEGER DEFAULT 1,
            caixa REAL DEFAULT 0,
            fat REAL DEFAULT 0,
            fixo REAL DEFAULT 0,
            margem REAL DEFAULT 30,
            modelo TEXT DEFAULT 'produtos',
            meta_fat REAL DEFAULT 0,
            ticket_medio REAL DEFAULT 0,
            tem_cac INTEGER DEFAULT 0,
            cac REAL DEFAULT 0,
            tem_ltv INTEGER DEFAULT 0,
            ltv REAL DEFAULT 0,
            tem_conversao INTEGER DEFAULT 0,
            taxa_conversao REAL DEFAULT 0,
            tem_ciclo INTEGER DEFAULT 0,
            ciclo_financeiro INTEGER DEFAULT 0,
            nome_pessoa TEXT DEFAULT '',
            cargo TEXT DEFAULT '',
            whatsapp TEXT DEFAULT '',
            historico_json TEXT DEFAULT '[]',
            atualizado_em TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


init_sqlite()


def supabase_rest(method, path, payload=None):
    if "COLE_AQUI" in SUPABASE_KEY or not SUPABASE_KEY:
        return False, "Chave SUPABASE_KEY não configurada"

    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    if method == "POST":
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = resp.read().decode("utf-8")
            return True, json.loads(body) if body else []
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        return False, f"HTTP {e.code}: {err_body}"
    except Exception as e:
        return False, str(e)


def disparar_whatsapp_automatico(whatsapp_lead, nome_pessoa, empresa, cnpj_limpo):
    if not WHATSAPP_API_URL or not WHATSAPP_API_TOKEN:
        return False, "API WhatsApp não configurada (modo manual ativo)"

    wpp_limpo = "".join(filter(str.isdigit, str(whatsapp_lead)))
    if not wpp_limpo.startswith("55"):
        wpp_limpo = "55" + wpp_limpo

    primeiro_nome = str(nome_pessoa).strip().split(" ")[0] if nome_pessoa else "Empresário(a)"
    texto = (
        f"Olá, *{primeiro_nome}*! Aqui é o *Doutor Caixa*.\n\n"
        f"O Laudo Executivo de Resiliência Financeira da *{empresa}* já está pronto.\n\n"
        f"Acesse seu diagnóstico completo e baixe o PDF por este link exclusivo:\n"
        f"https://doutor-caixa.onrender.com/laudo/{cnpj_limpo}"
    )

    payload = json.dumps({
        "number": wpp_limpo,
        "text": texto
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "apikey": WHATSAPP_API_TOKEN,
        "Authorization": f"Bearer {WHATSAPP_API_TOKEN}"
    }
    req = urllib.request.Request(WHATSAPP_API_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return True, resp.read().decode("utf-8")
    except Exception as e:
        print(f"AVISO DISPARO WHATSAPP: {e}")
        return False, str(e)


def notificar_novo_lead_telegram(dados):
    if not TELEGRAM_BOT_TOKEN or "COLE_AQUI" in TELEGRAM_BOT_TOKEN:
        return False, "Token do Telegram não configurado"

    wpp_limpo = "".join(filter(str.isdigit, str(dados.get("whatsapp", ""))))
    cegas = []
    controladas = []

    if dados.get("tem_cac"):
        controladas.append(f"CAC: R$ {format_brl(dados['cac'])}")
    else:
        cegas.append("CAC")

    if dados.get("tem_ltv"):
        controladas.append(f"LTV: R$ {format_brl(dados['ltv'])}")
    else:
        cegas.append("LTV")

    if dados.get("tem_conversao"):
        controladas.append(f"Conv.: {dados['taxa_conversao']}%")
    else:
        cegas.append("Taxa de Conversão")

    if dados.get("tem_ciclo"):
        controladas.append(f"Ciclo Fin.: {dados['ciclo_financeiro']} dias")
    else:
        cegas.append("Ciclo Financeiro")

    txt_controladas = ", ".join(controladas) if controladas else "Nenhuma (100% no escuro)"
    txt_cegas = ", ".join(cegas) if cegas else "Nenhuma (Operação monitorada)"

    tm = dados.get("ticket_medio", 0)
    fat = dados.get("fat", 0)
    meta = dados.get("meta_fat", 0)
    novas_vendas = max(0, math.ceil((meta - fat) / tm)) if tm > 0 else 0

    mensagem = (
        f"🚨 <b>NOVO LEAD DOUTOR CAIXA!</b>\n\n"
        f"👤 <b>Lead:</b> {html.escape(str(dados.get('nome_pessoa', '')))} ({html.escape(str(dados.get('cargo', '')))})\n"
        f"🏢 <b>Empresa:</b> {html.escape(str(dados.get('nome', '')))} [{dados.get('modelo', '').upper()}]\n"
        f"📱 <b>WhatsApp:</b> https://wa.me/55{wpp_limpo}\n\n"
        f"💰 <b>Fat. Atual:</b> R$ {format_brl(fat)} | <b>Caixa:</b> R$ {format_brl(dados.get('caixa', 0))}\n"
        f"🎯 <b>Meta:</b> R$ {format_brl(meta)} | <b>Ticket Médio:</b> R$ {format_brl(tm)}\n"
        f"📈 <b>Gap Comercial:</b> +{novas_vendas} vendas/mês para bater a meta\n\n"
        f"🟢 <b>Sabe/Controla:</b> {html.escape(txt_controladas)}\n"
        f"🔴 <b>Métricas Cegas:</b> {html.escape(txt_cegas)}\n\n"
        f"🔗 <b>Laudo Pronto:</b>\n"
        f"https://doutor-caixa.onrender.com/laudo/{dados.get('cnpj')}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({
        "chat_id": str(TELEGRAM_CHAT_ID).strip(),
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return True, resp.read().decode("utf-8")
    except Exception as e:
        print(f"ERRO TELEGRAM: {e}")
        return False, str(e)


def parse_brl(valor_str):
    if not valor_str:
        return 0.0
    limpo = str(valor_str).replace("R$", "").strip()
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    else:
        partes = limpo.split(".")
        if len(partes) > 1 and len(partes[-1]) == 3:
            limpo = limpo.replace(".", "")
    filtrado = "".join(c for c in limpo if c.isdigit() or c == ".")
    return float(filtrado) if filtrado else 0.0


def normalizar_cliente(row):
    margem_val = float(row.get("margem") or 30.0)
    if margem_val <= 0:
        margem_val = 30.0
    hist_raw = row.get("historico_json") or "[]"
    if isinstance(hist_raw, str):
        try:
            historico = json.loads(hist_raw)
        except Exception:
            historico = []
    elif isinstance(hist_raw, list):
        historico = hist_raw
    else:
        historico = []

    return {
        "cnpj": str(row.get("cnpj", "")),
        "nome": row.get("nome", "Empresa"),
        "ativo": bool(row.get("ativo", True)),
        "caixa": float(row.get("caixa") or 0.0),
        "fat": float(row.get("fat") or 0.0),
        "fixo": float(row.get("fixo") or 0.0),
        "margem": margem_val,
        "modelo": row.get("modelo") or "produtos",
        "meta_fat": float(row.get("meta_fat") or (float(row.get("fat") or 0.0) * 1.3)),
        "ticket_medio": float(row.get("ticket_medio") or 0.0),
        "tem_cac": bool(row.get("tem_cac", False)),
        "cac": float(row.get("cac") or 0.0),
        "tem_ltv": bool(row.get("tem_ltv", False)),
        "ltv": float(row.get("ltv") or 0.0),
        "tem_conversao": bool(row.get("tem_conversao", False)),
        "taxa_conversao": float(row.get("taxa_conversao") or 0.0),
        "tem_ciclo": bool(row.get("tem_ciclo", False)),
        "ciclo_financeiro": int(row.get("ciclo_financeiro") or 0),
        "nome_pessoa": row.get("nome_pessoa") or "",
        "cargo": row.get("cargo") or "",
        "whatsapp": row.get("whatsapp") or "",
        "historico": historico
    }


def buscar_cliente_db(cnpj_bruto):
    cnpj_limpo = "".join(filter(str.isdigit, str(cnpj_bruto)))

    # 1. Tenta Supabase Nuvem
    ok, dados = supabase_rest("GET", f"clientes_doutor_caixa?cnpj=eq.{cnpj_limpo}&select=*")
    if ok and isinstance(dados, list) and len(dados) > 0:
        return normalizar_cliente(dados[0])

    # 2. Tenta SQLite Local
    try:
        conn = sqlite3.connect(DB_LOCAL_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM clientes_doutor_caixa WHERE cnpj = ?", (cnpj_limpo,))
        row = cur.fetchone()
        conn.close()
        if row:
            return normalizar_cliente(dict(row))
    except Exception as e:
        print(f"ERRO BUSCA SQLITE: {e}")

    # 3. Exemplo padrão de demonstração
    if cnpj_limpo == "11222333000181":
        return normalizar_cliente({
            "cnpj": "11222333000181",
            "nome": "Comércio Exemplo RMR Ltda",
            "ativo": True,
            "caixa": 120000.00,
            "fat": 300000.00,
            "fixo": 95000.00,
            "margem": 38.0,
            "modelo": "produtos",
            "meta_fat": 400000.00,
            "ticket_medio": 2500.00,
            "tem_cac": False,
            "tem_ltv": False,
            "tem_conversao": True,
            "taxa_conversao": 18.0,
            "tem_ciclo": False
        })
    return None


def salvar_cliente_db(registro):
    cnpj_limpo = registro["cnpj"]

    # Verifica se já existe diagnóstico anterior para montar comparativo
    anterior = buscar_cliente_db(cnpj_limpo)
    historico = []
    if anterior and cnpj_limpo != "11222333000181":
        historico = anterior.get("historico", [])
        historico.append({
            "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "caixa": anterior["caixa"],
            "fat": anterior["fat"],
            "fixo": anterior["fixo"],
            "margem": anterior["margem"],
            "ticket_medio": anterior["ticket_medio"]
        })
        historico = historico[-5:]  # Mantém os últimos 5 registros

    registro["historico_json"] = json.dumps(historico, ensure_ascii=False)
    registro["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Salva no SQLite Local (garantia imediata)
    try:
        conn = sqlite3.connect(DB_LOCAL_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO clientes_doutor_caixa (
                cnpj, nome, ativo, caixa, fat, fixo, margem, modelo, meta_fat,
                ticket_medio, tem_cac, cac, tem_ltv, ltv, tem_conversao, taxa_conversao,
                tem_ciclo, ciclo_financeiro, nome_pessoa, cargo, whatsapp, historico_json, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cnpj_limpo, registro["nome"], 1, registro["caixa"], registro["fat"],
            registro["fixo"], registro["margem"], registro["modelo"], registro["meta_fat"],
            registro["ticket_medio"], int(registro["tem_cac"]), registro["cac"],
            int(registro["tem_ltv"]), registro["ltv"], int(registro["tem_conversao"]),
            registro["taxa_conversao"], int(registro["tem_ciclo"]), registro["ciclo_financeiro"],
            registro["nome_pessoa"], registro["cargo"], registro["whatsapp"],
            registro["historico_json"], registro["atualizado_em"]
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"ERRO GRAVAÇÃO SQLITE: {e}")

    # 2. Sincroniza com Supabase Nuvem (sem travar o cliente caso haja instabilidade de DNS)
    payload_sb = {
        "cnpj": cnpj_limpo,
        "nome": registro["nome"],
        "ativo": True,
        "caixa": registro["caixa"],
        "fat": registro["fat"],
        "fixo": registro["fixo"],
        "margem": registro["margem"],
        "modelo": registro["modelo"],
        "meta_fat": registro["meta_fat"],
        "ticket_medio": registro["ticket_medio"],
        "tem_cac": registro["tem_cac"],
        "cac": registro["cac"],
        "tem_ltv": registro["tem_ltv"],
        "ltv": registro["ltv"],
        "tem_conversao": registro["tem_conversao"],
        "taxa_conversao": registro["taxa_conversao"],
        "tem_ciclo": registro["tem_ciclo"],
        "ciclo_financeiro": registro["ciclo_financeiro"],
        "nome_pessoa": registro["nome_pessoa"],
        "cargo": registro["cargo"],
        "whatsapp": registro["whatsapp"],
        "historico_json": registro["historico_json"]
    }
    ok_sb, res_sb = supabase_rest("POST", "clientes_doutor_caixa?on_conflict=cnpj", payload_sb)
    if not ok_sb:
        print(f"AVISO SYNC SUPABASE: {res_sb}")

    return True, ok_sb


def format_brl(value):
    return "{:,.2f}".format(float(value)).replace(",", "X").replace(".", ",").replace("X", ".")


def format_cnpj(cnpj):
    c = "".join(filter(str.isdigit, str(cnpj)))
    if len(c) == 14:
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"
    return c


def pdf_safe(texto):
    # Remove emojis e caracteres fora do padrão latin-1 para evitar falha no FPDF
    return str(texto).encode("latin-1", "ignore").decode("latin-1")


app.jinja_env.filters['format_brl'] = format_brl
app.jinja_env.filters['format_cnpj'] = format_cnpj


@app.route('/favicon.ico')
def favicon():
    return send_file('static/favicon.png', mimetype='image/png')


@app.route('/teste-conexao')
def teste_conexao():
    try:
        ip_sb = socket.gethostbyname(f"{PROJECT_REF}.supabase.co")
        dns_status = f"OK ({ip_sb})"
    except Exception as e:
        dns_status = f"Falha DNS externa ({e})"

    ok_sb, res_sb = supabase_rest("GET", "clientes_doutor_caixa?select=cnpj&limit=5")
    status_sb = f"CONECTADO ({len(res_sb)} registros)" if ok_sb else f"Fallback SQLite Ativo ({res_sb})"

    conn = sqlite3.connect(DB_LOCAL_PATH)
    qtd_local = conn.execute("SELECT COUNT(*) FROM clientes_doutor_caixa").fetchone()[0]
    conn.close()

    return f"""
    <div style="font-family: sans-serif; padding: 30px; max-width: 680px; margin: auto;">
        <h2>Diagnóstico Técnico - Doutor Caixa v5.0</h2>
        <p><b>1. Banco Local (SQLite):</b> ATIVO ({qtd_local} registros salvos)</p>
        <p><b>2. DNS Supabase:</b> {dns_status}</p>
        <p><b>3. Sincronização Supabase:</b> {status_sb}</p>
        <p><b>4. Disparo WhatsApp API:</b> {'CONFIGURADO' if WHATSAPP_API_URL else 'Modo Manual (Link Direto Ativo)'}</p>
        <hr>
        <p><a href="/">Voltar para a Home</a></p>
    </div>
    """


# --- TEMPLATES HTML ---
TEMPLATE_HOME = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa | Inteligência Financeira B2B</title>
    <link rel="icon" type="image/png" href="/static/favicon.png">
    <link rel="shortcut icon" type="image/png" href="/static/favicon.png">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; background: #E8F7EE; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 16px; color: #0F2E1C; }
        .login-box { background: #FFFFFF; padding: 36px 30px; border-radius: 16px; box-shadow: 0 8px 28px rgba(15, 46, 28, 0.08); text-align: center; max-width: 440px; width: 100%; }
        .logo { max-width: 135px; margin-bottom: 14px; }
        h1 { color: #0F2E1C; margin: 0 0 8px 0; font-size: 22px; font-weight: 700; line-height: 1.25; }
        .subtitle { color: #6B7A70; font-size: 13.5px; margin: 0 0 22px 0; line-height: 1.5; }
        .btn-primary { display: block; background: #00C853; color: #FFFFFF; padding: 16px; width: 100%; border-radius: 10px; text-decoration: none; font-weight: 700; font-size: 15.5px; transition: background 0.2s; box-shadow: 0 4px 12px rgba(0, 200, 83, 0.25); }
        .btn-primary:hover { background: #00a645; }
        .btn-wpp-home { display: block; background: #E8F7EE; color: #0F2E1C; border: 1.5px solid #00C853; padding: 13px; width: 100%; border-radius: 10px; text-decoration: none; font-weight: 600; font-size: 14px; margin-top: 10px; transition: background 0.2s; }
        .btn-wpp-home:hover { background: #d4f0df; }
        .divider { display: flex; align-items: center; text-align: center; margin: 24px 0 18px 0; color: #8a9990; font-size: 12px; font-weight: 600; text-transform: uppercase; }
        .divider::before, .divider::after { content: ''; flex: 1; border-bottom: 1px solid #e2ece6; }
        .divider:not(:empty)::before { margin-right: 10px; }
        .divider:not(:empty)::after { margin-left: 10px; }
        input { width: 100%; padding: 14px; margin-bottom: 12px; border: 2px solid #E8F7EE; border-radius: 8px; font-family: 'Poppins', sans-serif; font-size: 15px; outline: none; text-align: center; }
        input:focus { border-color: #0F2E1C; }
        .btn-secondary { background: #0F2E1C; color: #FFFFFF; padding: 14px; width: 100%; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; font-family: 'Poppins', sans-serif; font-size: 14.5px; }
        .btn-secondary:hover { background: #18442a; }
        .erro-msg { background: #fdecea; color: #c0392b; font-size: 13px; padding: 10px; border-radius: 6px; margin-bottom: 14px; font-weight: 600; word-break: break-word; }
        .footer-seal { margin-top: 24px; padding-top: 16px; border-top: 1px solid #eef4f0; font-size: 11.5px; color: #7c8b82; line-height: 1.4; }
        .footer-seal strong { color: #0F2E1C; }
        @media (max-width: 480px) { body { background: #FFFFFF; padding: 0; align-items: flex-start; } .login-box { box-shadow: none; border-radius: 0; padding: 32px 20px; max-width: 100%; } }
    </style>
</head>
<body>
    <div class="login-box">
        <img src="/static/logo.png" alt="Doutor Caixa Logo" class="logo">
        <h1>Teste de Estresse & Resiliência de Caixa</h1>
        <p class="subtitle">Descubra em 2 minutos quanto tempo sua operação aguenta se as vendas caírem 30% e identifique gargalos ocultos de margem.</p>
        
        <a href="/diagnostico" class="btn-primary">🚀 Gerar Meu Diagnóstico Gratuito</a>
        <a href="https://wa.me/5581979091165?text=Olá!%20Vim%20pelo%20Doutor%20Caixa%20e%20gostaria%20de%20fazer%20uma%20triagem%20financeira%20e%20comercial%20com%20um%20especialista." target="_blank" class="btn-wpp-home">💬 Fazer Triagem via WhatsApp</a>

        <div class="divider">Já possui laudo?</div>

        {% if erro %}
            <div class="erro-msg">{{ erro }}</div>
        {% endif %}

        <form method="POST" action="/acessar">
            <input type="text" name="cnpj" inputmode="numeric" placeholder="Digite seu CNPJ (somente números)" required>
            <button type="submit" class="btn-secondary">Acessar Laudo Emitido</button>
        </form>

        <div class="footer-seal">
            🔒 Dados processados sob sigilo comercial (LGPD).<br>
            Uma solução de Inteligência Comercial <strong>MaqTrak</strong>.
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_SUCESSO = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa | Sucesso</title>
    <link rel="icon" type="image/png" href="/static/favicon.png">
    <link rel="shortcut icon" type="image/png" href="/static/favicon.png">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; background: #E8F7EE; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 16px; color: #0F2E1C; }
        .box { background: #FFFFFF; padding: 40px 30px; border-radius: 16px; box-shadow: 0 8px 28px rgba(15, 46, 28, 0.08); text-align: center; max-width: 440px; width: 100%; }
        .box h1 { color: #00C853; margin: 0 0 10px 0; font-size: 24px; }
        .box p { color: #6B7A70; font-size: 15px; line-height: 1.5; margin-bottom: 24px; }
        .alert-box { background: #f0fdf4; border: 2px solid #00C853; padding: 18px; border-radius: 10px; margin-bottom: 24px; }
        .alert-box strong { color: #0F2E1C; display: block; font-size: 16px; margin-bottom: 6px; }
        .alert-box span { color: #145c32; font-size: 14px; }
        .btn { display: block; background: #0F2E1C; color: #FFFFFF; padding: 16px; border-radius: 10px; text-decoration: none; font-weight: 600; font-size: 15px; }
    </style>
</head>
<body>
    <div class="box">
        <h1>✅ Diagnóstico Gerado!</h1>
        <p>Seus dados foram processados e salvos com sucesso na nossa base de inteligência.</p>
        
        <div class="alert-box">
            <strong>Fique atento ao seu WhatsApp!</strong>
            <span>O link exclusivo para você acessar a plataforma e baixar o seu Laudo Executivo em PDF será enviado em instantes para o número:<br><br><b>{{ whatsapp }}</b></span>
        </div>

        <a href="/" class="btn">Voltar para a Tela Inicial</a>
    </div>
</body>
</html>
"""

TEMPLATE_DIAGNOSTICO = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa | Novo Diagnóstico</title>
    <link rel="icon" type="image/png" href="/static/favicon.png">
    <link rel="shortcut icon" type="image/png" href="/static/favicon.png">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; background: #E8F7EE; margin: 0; padding: 24px 16px; color: #0F2E1C; }
        .form-container { max-width: 600px; margin: 0 auto; background: #FFFFFF; padding: 34px 32px; border-radius: 16px; box-shadow: 0 8px 28px rgba(15, 46, 28, 0.08); }
        .top-bar { display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #E8F7EE; padding-bottom: 14px; margin-bottom: 22px; }
        .logo { max-width: 115px; }
        .back-link { color: #6B7A70; text-decoration: none; font-size: 13px; font-weight: 600; }
        .back-link:hover { color: #0F2E1C; }
        h2 { margin: 0 0 6px 0; font-size: 20px; color: #0F2E1C; }
        .desc { margin: 0 0 22px 0; font-size: 13.5px; color: #6B7A70; line-height: 1.45; }
        
        .section-title { font-size: 12px; font-weight: 700; color: #00C853; text-transform: uppercase; letter-spacing: 0.5px; margin: 26px 0 12px 0; border-bottom: 1px solid #eef4f0; padding-bottom: 6px; }
        .section-sub { font-size: 12px; color: #6B7A70; margin: -6px 0 14px 0; line-height: 1.4; }
        
        .field-group { margin-bottom: 16px; }
        label { display: block; font-size: 13px; font-weight: 700; color: #0F2E1C; margin-bottom: 5px; }
        .hint { display: block; font-size: 11.5px; color: #6B7A70; margin-bottom: 6px; }
        input[type="text"], input[type="tel"], input[type="number"], select { width: 100%; padding: 13px 14px; border: 2px solid #E8F7EE; border-radius: 8px; font-family: 'Poppins', sans-serif; font-size: 14.5px; color: #0F2E1C; outline: none; background: #FFFFFF; transition: 0.2s; }
        input:focus, select:focus { border-color: #00C853; }
        .row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

        .wpp-box { background: #fff9e6; border: 1.5px solid #f39c12; padding: 14px; border-radius: 10px; margin-bottom: 16px; }
        .wpp-box label { color: #d35400; }
        .wpp-box .hint-alert { font-size: 11.5px; color: #b9770e; font-weight: 600; margin-bottom: 8px; display: block; line-height: 1.4; }
        .wpp-box input { border-color: #f5b041; }
        .wpp-box input:focus { border-color: #d35400; }

        /* ESTILO DOS TOGGLES DE MÉTRICAS CEGAS */
        .metric-card { background: #f8fbf9; border: 1.5px solid #e1ede6; border-radius: 10px; padding: 14px; margin-bottom: 12px; transition: 0.2s; }
        .metric-card.active { background: #f0fdf4; border-color: #00C853; }
        .metric-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; cursor: pointer; }
        .metric-info strong { display: block; font-size: 13.5px; color: #0F2E1C; }
        .metric-info span { display: block; font-size: 11.5px; color: #6B7A70; margin-top: 2px; }
        
        .switch { position: relative; display: inline-block; width: 48px; height: 26px; flex-shrink: 0; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #cbd5d0; transition: .3s; border-radius: 26px; }
        .slider:before { position: absolute; content: ""; height: 20px; width: 20px; left: 3px; bottom: 3px; background-color: white; transition: .3s; border-radius: 50%; }
        input:checked + .slider { background-color: #00C853; }
        input:checked + .slider:before { transform: translateX(22px); }

        .metric-input-box { display: none; margin-top: 12px; padding-top: 12px; border-top: 1px dashed #c8e6d4; }
        .metric-input-box.visible { display: block; }

        .btn-submit { background: #00C853; color: #FFFFFF; padding: 18px; width: 100%; border: none; border-radius: 10px; font-family: 'Poppins', sans-serif; font-size: 16px; font-weight: 700; cursor: pointer; margin-top: 14px; box-shadow: 0 4px 12px rgba(0, 200, 83, 0.25); transition: 0.2s; }
        .btn-submit:hover { background: #00a645; }
        .sigilo-box { margin-top: 18px; background: #f7faf8; padding: 12px; border-radius: 8px; font-size: 11.5px; color: #6B7A70; text-align: center; }

        @media (max-width: 540px) {
            body { background: #FFFFFF; padding: 0; }
            .form-container { box-shadow: none; border-radius: 0; padding: 22px 16px 36px 16px; max-width: 100%; }
            .row-2 { grid-template-columns: 1fr; gap: 0; }
        }
    </style>
</head>
<body>
    <div class="form-container">
        <div class="top-bar">
            <img src="/static/logo.png" alt="Doutor Caixa" class="logo">
            <a href="/" class="back-link">← Voltar</a>
        </div>

        <h2>Gerar Laudo Executivo</h2>
        <p class="desc">Insira os números aproximados da sua operação. O cálculo leva menos de 5 segundos.</p>

        <form method="POST" action="/diagnostico" onsubmit="return validarForm()">
            
            <div class="section-title">1. Dados do Solicitante</div>
            
            <div class="row-2">
                <div class="field-group">
                    <label>Seu Nome</label>
                    <input type="text" name="nome_pessoa" placeholder="Ex: Rodrigo Barros" required>
                </div>
                <div class="field-group">
                    <label>Seu Cargo</label>
                    <select name="cargo" required>
                        <option value="" disabled selected>Selecione...</option>
                        <option value="Sócio / CEO / Diretor">Sócio / CEO / Diretor</option>
                        <option value="Gerente Comercial / Vendas">Gerente Comercial / Vendas</option>
                        <option value="Gerente Financeiro">Gerente Financeiro</option>
                        <option value="Outros">Outros</option>
                    </select>
                </div>
            </div>

            <div class="wpp-box">
                <label>Número do WhatsApp</label>
                <span class="hint-alert">⚠️ Importante: O link de acesso à plataforma para visualizar seu laudo será enviado EXCLUSIVAMENTE para este número.</span>
                <input type="tel" name="whatsapp" id="whatsapp" placeholder="(81) 99999-9999" required>
            </div>

            <div class="section-title">2. Dados da Empresa</div>

            <div class="field-group">
                <label>Nome da Empresa</label>
                <input type="text" name="nome" placeholder="Ex: Distribuidora Recife Ltda" required>
            </div>

            <div class="field-group">
                <label>CNPJ Válido (Somente números)</label>
                <input type="text" name="cnpj" id="cnpj" inputmode="numeric" maxlength="18" placeholder="00.000.000/0000-00" required>
            </div>

            <div class="field-group">
                <label>Modelo de Negócio / Operação</label>
                <select name="modelo" required>
                    <option value="produtos">Comércio / Varejo / Distribuição (Produtos)</option>
                    <option value="servicos">Clínicas / Consultórios / Serviços por Agenda</option>
                    <option value="b2b">B2B Consultivo / Venda Complexa / Orçamentos</option>
                    <option value="campo">Prestadores de Serviço de Campo / Manutenção</option>
                </select>
            </div>

            <div class="section-title">3. Dados Financeiros & Comerciais</div>

            <div class="row-2">
                <div class="field-group">
                    <label>Saldo em Caixa Atual (R$)</label>
                    <span class="hint">Capital de giro disponível hoje</span>
                    <input type="text" name="caixa" class="moeda" inputmode="numeric" placeholder="120.000,00" required>
                </div>

                <div class="field-group">
                    <label>Faturamento Mensal (R$)</label>
                    <span class="hint">Média bruta mensal atual</span>
                    <input type="text" name="fat" class="moeda" inputmode="numeric" placeholder="300.000,00" required>
                </div>
            </div>

            <div class="row-2">
                <div class="field-group">
                    <label>Custo Fixo Mensal (R$)</label>
                    <span class="hint">Folha, aluguel, estrutura</span>
                    <input type="text" name="fixo" class="moeda" inputmode="numeric" placeholder="95.000,00" required>
                </div>

                <div class="field-group">
                    <label>Margem de Contribuição (%)</label>
                    <span class="hint">O que sobra pós-custo direto <b>(antes do Lucro Líquido)</b></span>
                    <input type="number" step="0.1" min="1" max="100" name="margem" inputmode="decimal" placeholder="Ex: 38" required>
                </div>
            </div>

            <div class="row-2">
                <div class="field-group">
                    <label>Ticket Médio das Vendas (R$)</label>
                    <span class="hint">Valor médio por venda / pedido fechado</span>
                    <input type="text" name="ticket_medio" class="moeda" inputmode="numeric" placeholder="2.500,00" required>
                </div>

                <div class="field-group">
                    <label>Meta de Faturamento Mensal (R$)</label>
                    <span class="hint">Onde você quer levar o faturamento</span>
                    <input type="text" name="meta_fat" class="moeda" inputmode="numeric" placeholder="450.000,00" required>
                </div>
            </div>

            <div class="section-title">4. Radar de Indicadores (Métricas Cegas)</div>
            <p class="section-sub">Ative a chave <b>apenas</b> para os indicadores que você realmente mede e tem certeza do número hoje. Se não souber, deixe desligado.</p>

            <!-- CAC -->
            <div class="metric-card" id="card_cac">
                <label class="metric-header" for="toggle_cac">
                    <div class="metric-info">
                        <strong>Sei meu CAC (Custo de Aquisição por Cliente)</strong>
                        <span>Quanto você investe em marketing + vendas para conquistar 1 cliente</span>
                    </div>
                    <div class="switch">
                        <input type="checkbox" id="toggle_cac" name="tem_cac" onchange="toggleMetrica('cac')">
                        <span class="slider"></span>
                    </div>
                </label>
                <div class="metric-input-box" id="box_cac">
                    <label>Informe seu CAC atual (R$)</label>
                    <input type="text" name="cac" id="input_cac" class="moeda" inputmode="numeric" placeholder="Ex: 350,00">
                </div>
            </div>

            <!-- LTV -->
            <div class="metric-card" id="card_ltv">
                <label class="metric-header" for="toggle_ltv">
                    <div class="metric-info">
                        <strong>Sei meu LTV (Lifetime Value)</strong>
                        <span>Quanto cada cliente deixa de receita ao longo de todo o relacionamento</span>
                    </div>
                    <div class="switch">
                        <input type="checkbox" id="toggle_ltv" name="tem_ltv" onchange="toggleMetrica('ltv')">
                        <span class="slider"></span>
                    </div>
                </label>
                <div class="metric-input-box" id="box_ltv">
                    <label>Informe seu LTV médio (R$)</label>
                    <input type="text" name="ltv" id="input_ltv" class="moeda" inputmode="numeric" placeholder="Ex: 4.800,00">
                </div>
            </div>

            <!-- TAXA DE CONVERSÃO -->
            <div class="metric-card" id="card_conv">
                <label class="metric-header" for="toggle_conv">
                    <div class="metric-info">
                        <strong>Sei minha Taxa de Conversão Comercial</strong>
                        <span>Percentual de propostas / contatos que viram venda fechada</span>
                    </div>
                    <div class="switch">
                        <input type="checkbox" id="toggle_conv" name="tem_conversao" onchange="toggleMetrica('conv')">
                        <span class="slider"></span>
                    </div>
                </label>
                <div class="metric-input-box" id="box_conv">
                    <label>Informe sua Taxa de Conversão (%)</label>
                    <input type="number" step="0.1" min="0.1" max="100" name="taxa_conversao" id="input_conv" inputmode="decimal" placeholder="Ex: 20">
                </div>
            </div>

            <!-- CICLO FINANCEIRO -->
            <div class="metric-card" id="card_ciclo">
                <label class="metric-header" for="toggle_ciclo">
                    <div class="metric-info">
                        <strong>Sei meu Ciclo Financeiro (Prazos)</strong>
                        <span>Diferença em dias entre pagar fornecedores e receber dos clientes</span>
                    </div>
                    <div class="switch">
                        <input type="checkbox" id="toggle_ciclo" name="tem_ciclo" onchange="toggleMetrica('ciclo')">
                        <span class="slider"></span>
                    </div>
                </label>
                <div class="metric-input-box" id="box_ciclo">
                    <label>Informe o Ciclo Financeiro (em dias)</label>
                    <input type="number" step="1" name="ciclo_financeiro" id="input_ciclo" inputmode="numeric" placeholder="Ex: 35">
                </div>
            </div>

            <button type="submit" class="btn-submit">📊 Processar Meus Dados</button>
        </form>

        <div class="sigilo-box">
            🔒 <strong>Sigilo Garantido:</strong> Dados processados sob rigorosos padrões da LGPD.
        </div>
    </div>

    <script>
        function toggleMetrica(key) {
            const chk = document.getElementById('toggle_' + key);
            const box = document.getElementById('box_' + key);
            const card = document.getElementById('card_' + key);
            const inp = document.getElementById('input_' + key);
            if (chk.checked) {
                box.classList.add('visible');
                card.classList.add('active');
                inp.required = true;
                inp.focus();
            } else {
                box.classList.remove('visible');
                card.classList.remove('active');
                inp.required = false;
                inp.value = '';
            }
        }

        function validarCNPJ(cnpj) {
            cnpj = cnpj.replace(/[^\\d]+/g,'');
            if(cnpj == '') return false;
            if (cnpj.length != 14) return false;
            if (/^(\\d)\\1+$/.test(cnpj)) return false;
            let tamanho = cnpj.length - 2
            let numeros = cnpj.substring(0,tamanho);
            let digitos = cnpj.substring(tamanho);
            let soma = 0;
            let pos = tamanho - 7;
            for (let i = tamanho; i >= 1; i--) {
              soma += numeros.charAt(tamanho - i) * pos--;
              if (pos < 2) pos = 9;
            }
            let resultado = soma % 11 < 2 ? 0 : 11 - soma % 11;
            if (resultado != digitos.charAt(0)) return false;
            tamanho = tamanho + 1;
            numeros = cnpj.substring(0,tamanho);
            soma = 0;
            pos = tamanho - 7;
            for (let i = tamanho; i >= 1; i--) {
              soma += numeros.charAt(tamanho - i) * pos--;
              if (pos < 2) pos = 9;
            }
            resultado = soma % 11 < 2 ? 0 : 11 - soma % 11;
            if (resultado != digitos.charAt(1)) return false;
            return true;
        }

        function validarForm() {
            let cnpjInput = document.getElementById('cnpj');
            if (!validarCNPJ(cnpjInput.value)) {
                alert("O CNPJ informado é inválido. Por favor, corrija.");
                cnpjInput.focus();
                return false;
            }
            
            let wppInput = document.getElementById('whatsapp');
            let wpp = wppInput.value.replace(/\\D/g, ''); 
            
            let regexCelularBR = /^[1-9]{2}9\\d{8}$/;
            if (!regexCelularBR.test(wpp)) {
                alert("Por favor, insira um número de celular válido com DDD (ex: 81 99999-9999).");
                wppInput.focus();
                return false;
            }
            return true;
        }

        document.getElementById('cnpj').addEventListener('input', function (e) {
            let v = e.target.value.replace(/\\D/g, '').slice(0, 14);
            v = v.replace(/^(\\d{2})(\\d)/, '$1.$2');
            v = v.replace(/^(\\d{2})\\.(\\d{3})(\\d)/, '$1.$2.$3');
            v = v.replace(/\\.(\\d{3})(\\d)/, '.$1/$2');
            v = v.replace(/(\\d{4})(\\d)/, '$1-$2');
            e.target.value = v;
        });

        document.getElementById('whatsapp').addEventListener('input', function (e) {
            let x = e.target.value.replace(/\\D/g, '').match(/(\\d{0,2})(\\d{0,5})(\\d{0,4})/);
            e.target.value = !x[2] ? x[1] : '(' + x[1] + ') ' + x[2] + (x[3] ? '-' + x[3] : '');
        });

        document.querySelectorAll('.moeda').forEach(function(input) {
            input.addEventListener('input', function(e) {
                let v = e.target.value.replace(/\\D/g, '');
                if (!v) { e.target.value = ''; return; }
                v = (parseInt(v, 10) / 100).toFixed(2) + '';
                v = v.replace('.', ',');
                v = v.replace(/(\\d)(?=(\\d{3})+(?!\\d))/g, '$1.');
                e.target.value = v;
            });
        });
    </script>
</body>
</html>
"""

TEMPLATE_DASHBOARD = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa | Laudo Financeiro</title>
    <link rel="icon" type="image/png" href="/static/favicon.png">
    <link rel="shortcut icon" type="image/png" href="/static/favicon.png">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root { --verde-caixa: #00C853; --verde-profundo: #0F2E1C; --menta-suave: #E8F7EE; --branco: #FFFFFF; --cinza-neutro: #6B7A70; --cor-alerta-texto: #c0392b; --cor-alerta-fundo: #fdeed9; --whatsapp: #25D366; --azul-metrica: #2980b9; --azul-fundo: #ebf5fb; }
        * { box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; background: var(--menta-suave); margin: 0; padding: 24px 16px; color: var(--verde-profundo); -webkit-font-smoothing: antialiased; }
        .container { max-width: 820px; margin: 0 auto; background: var(--branco); padding: 36px; border-radius: 14px; box-shadow: 0 6px 20px rgba(15, 46, 28, 0.06); }
        .header { display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid var(--menta-suave); padding-bottom: 18px; margin-bottom: 24px; gap: 16px; }
        .logo { max-width: 150px; height: auto; }
        .header-titles { text-align: right; }
        .header h1 { color: var(--verde-profundo); font-size: 24px; margin: 0; font-weight: 700; line-height: 1.2; }
        .header span { font-size: 12px; color: var(--cinza-neutro); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
        .paciente-box { background: #f7faf8; padding: 14px 18px; border-radius: 8px; margin-bottom: 20px; border-left: 5px solid var(--verde-profundo); }
        .paciente-box p { margin: 0; font-size: 16px; color: var(--cinza-neutro); }
        .paciente-box strong { color: var(--verde-profundo); }
        .paciente-box small { display: block; margin-top: 2px; font-size: 13px; color: var(--cinza-neutro); }
        .hist-box { background: #eef9f2; border: 1.5px solid #00C853; border-radius: 8px; padding: 12px 16px; margin-bottom: 18px; font-size: 13.5px; color: #0F2E1C; }
        .card { background: var(--menta-suave); padding: 18px 20px; border-radius: 10px; margin-bottom: 14px; border-left: 5px solid var(--verde-caixa); }
        .card-label { color: var(--cinza-neutro); font-weight: 700; font-size: 14px; }
        .alert-red { border-left-color: var(--cor-alerta-texto); background: var(--cor-alerta-fundo); }
        .alert-green { border-left-color: var(--verde-caixa); background: var(--menta-suave); }
        .alert-blue { border-left-color: var(--azul-metrica); background: var(--azul-fundo); }
        .value { font-size: 26px; font-weight: 700; color: var(--verde-profundo); margin-top: 4px; }
        .value.red { color: var(--cor-alerta-texto); }
        .value.blue { color: var(--azul-metrica); }
        .helper-text { font-size: 12px; color: var(--cinza-neutro); margin-top: 4px; }
        .engenharia-box { background: #ffffff; border: 1px solid #bcd9ea; border-radius: 8px; padding: 12px 14px; margin-top: 10px; font-size: 13px; color: #1b4f72; }
        .prescricao-card { background: var(--verde-profundo); border-left: 5px solid var(--verde-caixa); color: var(--branco); padding: 22px 20px; border-radius: 10px; margin-bottom: 16px; }
        .prescricao-title { color: var(--verde-caixa); font-size: 16px; font-weight: 700; margin-bottom: 14px; letter-spacing: 0.3px; }
        .lista-acoes p { margin: 0 0 12px 0; color: #f0f4f1; font-size: 15px; line-height: 1.5; }
        .lista-acoes p:last-child { margin-bottom: 0; }
        .lista-acoes strong { color: var(--branco); font-weight: 700; }
        .metricas-cegas-card { background: #fff5f5; border: 2px solid #e74c3c; border-left: 6px solid #c0392b; border-radius: 10px; padding: 22px 20px; margin: 18px 0; }
        .metricas-cegas-card.all-ok { background: #f0fdf4; border-color: #00C853; border-left-color: #00C853; }
        .mc-badge { display: inline-block; background: #c0392b; color: #ffffff; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 4px; letter-spacing: 0.6px; text-transform: uppercase; margin-bottom: 8px; }
        .mc-badge.ok { background: #00C853; }
        .mc-title { color: #922b21; font-size: 18px; font-weight: 700; margin: 0 0 8px 0; }
        .mc-title.ok { color: #0F2E1C; }
        .mc-intro { color: #333333; font-size: 14px; margin: 0 0 14px 0; line-height: 1.5; }
        .mc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }
        .mc-item { background: #ffffff; border: 1px solid #f5b7b1; border-left: 4px solid #c0392b; border-radius: 6px; padding: 10px 12px; }
        .mc-item.ok { border-color: #b7e4c7; border-left-color: #00C853; }
        .mc-item strong { display: block; color: #c0392b; font-size: 13px; margin-bottom: 3px; }
        .mc-item.ok strong { color: #0F2E1C; }
        .mc-item span { display: block; color: #4a4a4a; font-size: 12.5px; line-height: 1.4; }
        .mc-footer { margin: 0; font-size: 13.5px; font-weight: 700; color: #922b21; }
        .consequencia { background: #fdeed9; border-left: 5px solid #d35400; padding: 16px 18px; margin-bottom: 20px; border-radius: 10px; }
        .consequencia h4 { color: #a04000; margin: 0 0 6px 0; font-size: 15px; font-weight: 700; }
        .consequencia p { color: #333333; margin: 0; font-size: 14px; line-height: 1.5; }
        .botoes { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
        .btn { background: var(--verde-caixa); color: var(--branco); padding: 15px 18px; text-decoration: none; border-radius: 8px; font-weight: 700; text-align: center; flex: 1; min-width: 200px; transition: background 0.2s; font-size: 15px; display: flex; align-items: center; justify-content: center; }
        .btn:hover { background: #00a645; }
        .btn-outline { background: transparent; border: 2px solid var(--verde-profundo); color: var(--verde-profundo); }
        .btn-outline:hover { background: var(--verde-profundo); color: var(--branco); }
        .btn-wpp { background: var(--whatsapp); color: #ffffff; }
        .btn-wpp:hover { background: #1ebe57; }
        @media (max-width: 640px) { body { padding: 0; background: var(--branco); } .container { max-width: 100%; border-radius: 0; box-shadow: none; padding: 20px 16px 32px 16px; } .header { flex-direction: row; align-items: center; padding-bottom: 14px; margin-bottom: 18px; } .logo { max-width: 110px; } .header h1 { font-size: 18px; } .header span { font-size: 10px; } .card { padding: 15px 16px; margin-bottom: 12px; } .card-label { font-size: 13px; } .value { font-size: 22px; } .mc-grid { grid-template-columns: 1fr; } .metricas-cegas-card { padding: 16px; } .mc-title { font-size: 16px; } .botoes { flex-direction: column; gap: 10px; } .btn { width: 100%; min-width: 100%; padding: 16px; font-size: 15px; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="/static/logo.png" alt="Doutor Caixa Logo" class="logo">
            <div class="header-titles">
                <span>Diagnóstico Executivo</span>
                <h1>Laudo de Resiliência</h1>
            </div>
        </div>
        
        <div class="paciente-box">
            <p>Paciente (Empresa): <strong>{{ cliente.nome }}</strong></p>
            <small>CNPJ: {{ cnpj|format_cnpj }} | Setor: <strong>{{ cliente.modelo|upper }}</strong>{% if cliente.ticket_medio > 0 %} | Ticket Médio: <strong>R$ {{ cliente.ticket_medio|format_brl }}</strong>{% endif %}</small>
        </div>

        {% if comparativo %}
        <div class="hist-box">
            📈 <strong>Evolução vs. Última Consulta ({{ comparativo.data }}):</strong><br>
            Caixa: <strong>{{ comparativo.diff_caixa }}</strong> | Faturamento: <strong>{{ comparativo.diff_fat }}</strong>
        </div>
        {% endif %}
        
        <div class="card alert-blue">
            <div class="card-label">Ponto de Equilíbrio (Faturamento Mínimo Mensal)</div>
            <div class="value blue">R$ {{ ponto_equilibrio|format_brl }}</div>
            <div class="helper-text">*Faturamento necessário para cobrir todos os custos e não ter prejuízo{% if vendas_pe > 0 %} (equivale a <b>{{ vendas_pe }} vendas/mês</b> no seu ticket médio){% endif %}.</div>
        </div>
        
        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div class="card-label">Faturamento Projetado (Pior Cenário -30%)</div>
            <div class="value">R$ {{ fat_estresse|format_brl }}</div>
        </div>

        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div class="card-label">Lucro Líquido Projetado (Cenário de Estresse)</div>
            <div class="value {% if lucro < 0 %}red{% endif %}">R$ {{ lucro|format_brl }}</div>
        </div>

        <div class="card alert-blue">
            <div class="card-label">Projeção na Meta de Faturamento Desejada (R$ {{ meta_fat|format_brl }})</div>
            <div class="value blue" style="font-size: 22px;">
                Crescimento de +{{ "%.1f"|format(crescimento_necessario) }}% | Lucro na Meta: R$ {{ lucro_na_meta|format_brl }}
            </div>
            <div class="helper-text">*Lucro Líquido projetado mantendo sua estrutura e margem atual de {{ cliente.margem }}%.</div>
            {% if cliente.ticket_medio > 0 %}
            <div class="engenharia-box">
                🎯 <strong>Engenharia Reversa Comercial (Ticket Médio R$ {{ cliente.ticket_medio|format_brl }}):</strong><br>
                Hoje você fecha ~<b>{{ vendas_atuais }} vendas/mês</b>. Para atingir a meta de R$ {{ meta_fat|format_brl }}, você precisa de <b>{{ vendas_meta }} vendas/mês</b> (um incremento de <b>+{{ novas_vendas }} novas vendas</b>).
                {% if cliente.tem_conversao and cliente.taxa_conversao > 0 %}
                <br>Com sua taxa de conversão de <b>{{ cliente.taxa_conversao }}%</b>, o comercial precisa gerar <b>{{ leads_necessarios }} propostas/oportunidades qualificadas por mês</b>.
                {% endif %}
            </div>
            {% endif %}
        </div>

        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div class="card-label">Status Clínico do Caixa (Runway)</div>
            <div class="value {% if lucro < 0 %}red{% endif %}" style="font-size: 18px;">
                {% if lucro < 0 %}
                    🔴 CRÍTICO: Hemorragia de caixa. Fôlego para {{ "%.1f"|format(meses_runway) }} meses.
                {% else %}
                    🟢 ESTÁVEL: Caixa blindado e margem segura na crise.
                {% endif %}
            </div>
        </div>

        <div class="prescricao-card">
            <div class="prescricao-title">PRESCRIÇÃO ESTRATÉGICA (O QUE FAZER AGORA?)</div>
            <div class="lista-acoes">
                {% for item in acao %}
                    <p>{{ item|safe }}</p>
                {% endfor %}
            </div>
        </div>

        <div class="metricas-cegas-card {% if qtd_cegas == 0 %}all-ok{% endif %}">
            {% if qtd_cegas > 0 %}
                <span class="mc-badge">🚨 {{ qtd_cegas }} de 4 Indicadores Cegos Detectados</span>
                <h3 class="mc-title">RADAR DE MÉTRICAS: PONTOS CEGOS NA OPERAÇÃO</h3>
                <p class="mc-intro">Com base no seu preenchimento, mapeamos o nível de controle da sua gestão comercial e financeira:</p>
            {% else %}
                <span class="mc-badge ok">✅ Alta Maturidade de Gestão</span>
                <h3 class="mc-title ok">RADAR DE MÉTRICAS: 100% MONITORADO</h3>
                <p class="mc-intro">Sua operação monitora os 4 indicadores vitais de escala e caixa:</p>
            {% endif %}

            <div class="mc-grid">
                {% for m in radar_metricas %}
                <div class="mc-item {% if m.controlada %}ok{% endif %}">
                    <strong>{% if m.controlada %}🟢{% else %}🔴{% endif %} {{ m.titulo }}</strong>
                    <span>{{ m.descricao }}</span>
                </div>
                {% endfor %}
            </div>

            {% if qtd_cegas > 0 %}
                <p class="mc-footer">Pilotar sem esses {{ qtd_cegas }} indicador(es) significa queimar margem todos os dias no escuro.</p>
            {% endif %}
        </div>
        
        {% if lucro < 0 %}
        <div class="consequencia">
            <h4>⚠️ CONSEQUÊNCIA DA INAÇÃO</h4>
            <p>Se as medidas acima não forem aplicadas imediatamente, o capital de giro da empresa será consumido em <strong>{{ "%.1f"|format(meses_runway) }} meses</strong>, resultando em paralisação operacional ou captação de crédito a juros predatórios.</p>
        </div>
        {% endif %}

        <div class="botoes">
            <a href="https://wa.me/5581979091165?text=Olá,%20acabei%20de%20gerar%20meu%20laudo%20no%20Doutor%20Caixa%20({{ cliente.nome }})%20e%20preciso%20de%20ajuda%20estratégica." target="_blank" class="btn btn-wpp">💬 Falar com Especialista Agora</a>
            <a href="/baixar_pdf/{{ cnpj }}" class="btn">📄 Baixar Laudo PDF</a>
            <a href="/" class="btn btn-outline">Nova Consulta</a>
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_BLOQUEIO = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa | Acesso Bloqueado</title>
    <link rel="icon" type="image/png" href="/static/favicon.png">
    <link rel="shortcut icon" type="image/png" href="/static/favicon.png">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; }
        body { font-family: 'Poppins', sans-serif; background: #fdeed9; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; padding: 16px; }
        .box { text-align: center; background: white; padding: 40px 28px; border-radius: 14px; box-shadow: 0 4px 15px rgba(0,0,0,0.08); max-width: 420px; width: 100%; }
        .btn-wpp { background: #25D366; color: white; padding: 16px; width: 100%; border-radius: 8px; text-decoration: none; font-weight: 700; display: inline-block; margin-top: 20px; }
        .btn-wpp:hover { background: #1ebe57; }
    </style>
</head>
<body>
    <div class="box">
        <img src="/static/logo.png" alt="Doutor Caixa Logo" style="max-width: 140px; margin-bottom: 18px;">
        <h2 style="color:#c0392b; margin-top: 0;">Acesso Bloqueado</h2>
        <p style="color: #6B7A70; font-size: 14px;">Sua assinatura do Doutor Caixa encontra-se pendente ou o período gratuito expirou.</p>
        <a href="https://wa.me/5581979091165?text=Olá,%20meu%20acesso%20ao%20Doutor%20Caixa%20está%20bloqueado.%20Como%20faço%20para%20renovar?" target="_blank" class="btn-wpp">💬 Renovar Acesso no WhatsApp</a>
    </div>
</body>
</html>
"""


def calcular_metricas_laudo(cliente):
    margem_pct = cliente['margem'] if cliente['margem'] > 0 else 30.0
    fat_estresse = cliente['fat'] * 0.70
    lucro = (fat_estresse * (margem_pct / 100)) - cliente['fixo']
    meses_runway = cliente['caixa'] / abs(lucro) if lucro < 0 else 0
    ponto_equilibrio = cliente['fixo'] / (margem_pct / 100)

    meta_fat = cliente['meta_fat']
    crescimento_necessario = ((meta_fat - cliente['fat']) / cliente['fat']) * 100 if cliente['fat'] > 0 else 0
    lucro_na_meta = (meta_fat * (margem_pct / 100)) - cliente['fixo']

    tm = cliente.get('ticket_medio', 0.0)
    vendas_atuais = math.ceil(cliente['fat'] / tm) if tm > 0 else 0
    vendas_meta = math.ceil(meta_fat / tm) if tm > 0 else 0
    vendas_pe = math.ceil(ponto_equilibrio / tm) if tm > 0 else 0
    novas_vendas = max(0, vendas_meta - vendas_atuais)
    leads_necessarios = math.ceil(vendas_meta / (cliente['taxa_conversao'] / 100)) if (cliente.get('tem_conversao') and cliente.get('taxa_conversao', 0) > 0) else 0

    # Radar de Métricas Cegas vs Controladas
    radar = []
    qtd_cegas = 0

    if cliente.get('tem_cac'):
        radar.append({
            "controlada": True,
            "titulo": f"1. CAC Controlado: R$ {format_brl(cliente['cac'])}",
            "descricao": "Você já mede o custo de aquisição. Próximo passo: otimizar canais de menor CAC."
        })
    else:
        qtd_cegas += 1
        radar.append({
            "controlada": False,
            "titulo": "1. CAC (Métrica Cega)",
            "descricao": "Você não sabe quanto custa colocar cada novo cliente para dentro da empresa."
        })

    if cliente.get('tem_ltv'):
        rel_ltv_cac = ""
        if cliente.get('tem_cac') and cliente.get('cac', 0) > 0:
            ratio = cliente['ltv'] / cliente['cac']
            rel_ltv_cac = f" (Relação LTV/CAC: {ratio:.1f}x - {'Saudável' if ratio >= 3 else 'Atenção: ideal >= 3x'})."
        radar.append({
            "controlada": True,
            "titulo": f"2. LTV Controlado: R$ {format_brl(cliente['ltv'])}",
            "descricao": f"Receita por cliente mapeada.{rel_ltv_cac}"
        })
    else:
        qtd_cegas += 1
        radar.append({
            "controlada": False,
            "titulo": "2. LTV (Métrica Cega)",
            "descricao": "Desconhece o lucro real que cada cliente deixa ao longo de todo o relacionamento."
        })

    if cliente.get('tem_conversao'):
        radar.append({
            "controlada": True,
            "titulo": f"3. Taxa de Conversão: {cliente['taxa_conversao']}%",
            "descricao": f"Funil rastreado. Necessário gerar ~{leads_necessarios} oportunidades/mês para a meta." if leads_necessarios > 0 else "Taxa de fechamento comercial acompanhada."
        })
    else:
        qtd_cegas += 1
        radar.append({
            "controlada": False,
            "titulo": "3. Taxa de Conversão (Métrica Cega)",
            "descricao": "Falta rastreabilidade exata entre prospecção, orçamentos e fechamento."
        })

    if cliente.get('tem_ciclo'):
        dias = cliente['ciclo_financeiro']
        aviso_ciclo = "Alerta: ciclo longo exige alto capital de giro." if dias > 30 else "Ciclo financeiro sob controle."
        radar.append({
            "controlada": True,
            "titulo": f"4. Ciclo Financeiro: {dias} dias",
            "descricao": f"Prazo médio mapeado. {aviso_ciclo}"
        })
    else:
        qtd_cegas += 1
        radar.append({
            "controlada": False,
            "titulo": "4. Ciclo Financeiro (Métrica Cega)",
            "descricao": "Risco de descasamento entre prazos de recebimento e pagamento corroer o caixa."
        })

    # Histórico comparativo
    comparativo = None
    hist = cliente.get("historico", [])
    if hist and len(hist) > 0:
        ult = hist[-1]
        d_caixa = cliente["caixa"] - float(ult.get("caixa", 0))
        d_fat = cliente["fat"] - float(ult.get("fat", 0))
        s_caixa = f"+R$ {format_brl(d_caixa)}" if d_caixa >= 0 else f"-R$ {format_brl(abs(d_caixa))}"
        s_fat = f"+R$ {format_brl(d_fat)}" if d_fat >= 0 else f"-R$ {format_brl(abs(d_fat))}"
        comparativo = {
            "data": ult.get("data", "Anterior"),
            "diff_caixa": s_caixa,
            "diff_fat": s_fat
        }

    return {
        "margem_pct": margem_pct,
        "fat_estresse": fat_estresse,
        "lucro": lucro,
        "meses_runway": meses_runway,
        "ponto_equilibrio": ponto_equilibrio,
        "meta_fat": meta_fat,
        "crescimento_necessario": crescimento_necessario,
        "lucro_na_meta": lucro_na_meta,
        "vendas_atuais": vendas_atuais,
        "vendas_meta": vendas_meta,
        "vendas_pe": vendas_pe,
        "novas_vendas": novas_vendas,
        "leads_necessarios": leads_necessarios,
        "radar_metricas": radar,
        "qtd_cegas": qtd_cegas,
        "comparativo": comparativo
    }


def renderizar_laudo(cnpj_limpo):
    cliente = buscar_cliente_db(cnpj_limpo)
    if not cliente:
        return render_template_string(TEMPLATE_HOME, erro="CNPJ não encontrado. Por favor, gere um novo diagnóstico.")

    if not cliente['ativo']:
        return render_template_string(TEMPLATE_BLOQUEIO)

    m = calcular_metricas_laudo(cliente)
    modelo = cliente.get('modelo', 'produtos')

    if modelo == 'servicos':
        acao_modelo = "<strong>Gargalo de Agenda:</strong> Implantar confirmação ativa e lista de espera automatizada para zerar o prejuízo de horários vagos e no-shows."
    elif modelo == 'b2b':
        acao_modelo = "<strong>Gargalo Comercial:</strong> Estruturar cadência ativa de 30 contatos/dia e funil de recuperação de orçamentos parados."
    elif modelo == 'campo':
        acao_modelo = "<strong>Gargalo de Campo:</strong> Criar esteira de contratos de manutenção preventiva recorrente e roteirização de equipes."
    else:
        acao_modelo = "<strong>Gargalo de Varejo:</strong> Treinar equipe de balcão/WhatsApp para venda de valor e blindagem da margem de contribuição."

    txt_meta_vendas = f" (+{m['novas_vendas']} vendas/mês no ticket médio atual)" if m['novas_vendas'] > 0 else ""

    if m['lucro'] < 0:
        acao = [
            "<strong>1. REESTRUTURAÇÃO IMEDIATA:</strong> Reduzir custos fixos não essenciais em pelo menos 15%.",
            f"<strong>2. INTELIGÊNCIA COMERCIAL:</strong> {acao_modelo}",
            "<strong>3. PROTEÇÃO DE CAPITAL:</strong> Congelar antecipações de recebíveis e renegociar prazos com fornecedores."
        ]
    else:
        acao = [
            "<strong>1. EXPANSÃO ESTRATÉGICA:</strong> Utilizar a resiliência do caixa para campanhas de aquisição de novos clientes.",
            f"<strong>2. BLINDAGEM DE MARGEM:</strong> {acao_modelo}",
            f"<strong>3. ESCALA DE VENDAS:</strong> Subir a régua de contatos diários focando em atingir a meta de R$ {format_brl(m['meta_fat'])}{txt_meta_vendas}."
        ]

    return render_template_string(
        TEMPLATE_DASHBOARD,
        cliente=cliente,
        cnpj=cnpj_limpo,
        acao=acao,
        **m
    )


@app.route('/')
def home():
    return render_template_string(TEMPLATE_HOME, erro=None)


@app.route('/diagnostico', methods=['GET', 'POST'])
def diagnostico():
    if request.method == 'GET':
        return render_template_string(TEMPLATE_DIAGNOSTICO)

    try:
        cnpj_limpo = "".join(filter(str.isdigit, request.form.get('cnpj', '')))
        if not cnpj_limpo:
            return render_template_string(TEMPLATE_HOME, erro="Por favor, informe um CNPJ válido.")

        fat = parse_brl(request.form.get('fat', '0'))
        margem = float(str(request.form.get('margem', '30')).replace(',', '.'))
        if margem <= 0:
            margem = 30.0

        tem_cac = 'tem_cac' in request.form
        tem_ltv = 'tem_ltv' in request.form
        tem_conversao = 'tem_conversao' in request.form
        tem_ciclo = 'tem_ciclo' in request.form

        registro = {
            "cnpj": cnpj_limpo,
            "nome_pessoa": request.form.get('nome_pessoa', '').strip(),
            "cargo": request.form.get('cargo', '').strip(),
            "whatsapp": "".join(filter(str.isdigit, request.form.get('whatsapp', ''))),
            "nome": request.form.get('nome', 'Empresa Consultada').strip(),
            "modelo": request.form.get('modelo', 'produtos'),
            "caixa": parse_brl(request.form.get('caixa', '0')),
            "fat": fat,
            "fixo": parse_brl(request.form.get('fixo', '0')),
            "margem": margem,
            "ticket_medio": parse_brl(request.form.get('ticket_medio', '0')),
            "meta_fat": parse_brl(request.form.get('meta_fat', str(fat * 1.3))),
            "tem_cac": tem_cac,
            "cac": parse_brl(request.form.get('cac', '0')) if tem_cac else 0.0,
            "tem_ltv": tem_ltv,
            "ltv": parse_brl(request.form.get('ltv', '0')) if tem_ltv else 0.0,
            "tem_conversao": tem_conversao,
            "taxa_conversao": float(str(request.form.get('taxa_conversao', '0')).replace(',', '.')) if tem_conversao else 0.0,
            "tem_ciclo": tem_ciclo,
            "ciclo_financeiro": int(float(request.form.get('ciclo_financeiro', '0') or 0)) if tem_ciclo else 0
        }

        salvar_cliente_db(registro)
        notificar_novo_lead_telegram(registro)
        disparar_whatsapp_automatico(
            request.form.get('whatsapp', ''),
            registro["nome_pessoa"],
            registro["nome"],
            cnpj_limpo
        )

        return render_template_string(TEMPLATE_SUCESSO, whatsapp=request.form.get('whatsapp', ''))
    except Exception as e:
        print(traceback.format_exc())
        return render_template_string(TEMPLATE_HOME, erro=f"Erro interno no processamento: {str(e)}")


@app.route('/acessar', methods=['GET', 'POST'])
def acessar():
    if request.method == 'GET':
        return redirect(url_for('home'))
    cnpj_limpo = "".join(filter(str.isdigit, request.form.get('cnpj', '')))
    return renderizar_laudo(cnpj_limpo)


@app.route('/laudo/<cnpj>')
def laudo_direto(cnpj):
    cnpj_limpo = "".join(filter(str.isdigit, str(cnpj)))
    return renderizar_laudo(cnpj_limpo)


@app.route('/baixar_pdf/<cnpj>')
def baixar_pdf(cnpj):
    cliente = buscar_cliente_db(cnpj)
    if not cliente:
        return "Erro", 404

    m = calcular_metricas_laudo(cliente)
    is_critical = m['lucro'] < 0

    class PDF(FPDF):
        def header(self):
            try:
                self.image('static/logo.png', 12, 9, 30)
            except Exception:
                pass
            self.set_text_color(15, 46, 28)
            self.set_font('helvetica', 'B', 16)
            self.set_xy(50, 16)
            self.cell(148, 8, 'LAUDO CLÍNICO FINANCEIRO', border=0, align='R')
            self.set_font('helvetica', '', 8.5)
            self.set_text_color(107, 122, 112)
            self.set_xy(50, 24)
            self.cell(148, 6, 'DIAGNÓSTICO DE RESILIÊNCIA E INTELIGÊNCIA DE CAIXA', border=0, align='R')
            self.set_draw_color(213, 232, 220)
            self.set_line_width(0.4)
            self.line(12, 43, 198, 43)
            self.set_y(49)

        def footer(self):
            self.set_y(-14)
            self.set_font('helvetica', '', 8)
            self.set_text_color(130, 140, 134)
            self.cell(0, 8, f'Doutor Caixa | Inteligência Financeira & Comercial  -  Página {self.page_no()}', align='C')

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    def desenhar_card(y_topo, altura, cor_fundo, cor_barra):
        pdf.set_fill_color(*cor_fundo)
        pdf.rect(12, y_topo, 186, altura, 'F')
        pdf.set_fill_color(*cor_barra)
        pdf.rect(12, y_topo, 2.5, altura, 'F')

    # 1. Identificação do Paciente
    y = pdf.get_y()
    desenhar_card(y, 19, (247, 250, 248), (15, 46, 28))
    pdf.set_xy(19, y + 3.5)
    pdf.set_font('helvetica', 'B', 11)
    pdf.set_text_color(15, 46, 28)
    pdf.cell(175, 6, pdf_safe(f"PACIENTE (EMPRESA): {cliente['nome']}"), ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 9.5)
    pdf.set_text_color(107, 122, 112)
    tm_txt = f"  |  Ticket Médio: R$ {format_brl(cliente['ticket_medio'])}" if cliente['ticket_medio'] > 0 else ""
    pdf.cell(175, 5.5, pdf_safe(f"CNPJ: {format_cnpj(cnpj)}  |  Setor: {cliente['modelo'].upper()}{tm_txt}"), ln=1)
    pdf.set_y(y + 19 + 6)

    # 2. Ponto de Equilíbrio
    y = pdf.get_y()
    desenhar_card(y, 24, (235, 245, 251), (41, 128, 185))
    pdf.set_xy(19, y + 3)
    pdf.set_font('helvetica', 'B', 9)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 5, "PONTO DE EQUILÍBRIO (FATURAMENTO MÍNIMO MENSAL)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 16)
    pdf.set_text_color(41, 128, 185)
    pdf.cell(175, 7.5, f"R$ {format_brl(m['ponto_equilibrio'])}", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 8)
    pdf.set_text_color(107, 122, 112)
    pe_vendas = f" ({m['vendas_pe']} vendas/mês no ticket médio atual)" if m['vendas_pe'] > 0 else ""
    pdf.cell(175, 4.5, pdf_safe(f"Faturamento mínimo para cobrir custos fixos e variáveis sem prejuízo{pe_vendas}."), ln=1)
    pdf.set_y(y + 24 + 6)

    # 3. Cenário de Estresse
    y = pdf.get_y()
    bg_color = (253, 237, 236) if is_critical else (232, 247, 238)
    bar_color = (192, 57, 43) if is_critical else (0, 200, 83)
    val_color = (192, 57, 43) if is_critical else (15, 46, 28)
    status_text = "PREJUÍZO / QUEIMA DE CAIXA" if is_critical else "CAIXA BLINDADO"
    desenhar_card(y, 27, bg_color, bar_color)
    pdf.set_xy(19, y + 3)
    pdf.set_font('helvetica', 'B', 9)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 5, "DIAGNÓSTICO DE ESTRESSE (CENÁRIO DE QUEDA DE 30% NO FATURAMENTO)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 9.5)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(175, 5.5, f"Faturamento Projetado: R$ {format_brl(m['fat_estresse'])}   |   Lucro Líquido Projetado:", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 14.5)
    pdf.set_text_color(*val_color)
    pdf.cell(175, 8, f"R$ {format_brl(m['lucro'])}   ({status_text})", ln=1)
    pdf.set_y(y + 27 + 6)

    # 4. Projeção na Meta + Engenharia Reversa
    y = pdf.get_y()
    alt_meta = 31 if cliente['ticket_medio'] > 0 else 24
    desenhar_card(y, alt_meta, (235, 245, 251), (41, 128, 185))
    pdf.set_xy(19, y + 3)
    pdf.set_font('helvetica', 'B', 9)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 5, f"PROJEÇÃO NA META DESEJADA (R$ {format_brl(m['meta_fat'])})", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 11.5)
    pdf.set_text_color(41, 128, 185)
    pdf.cell(175, 6.5, f"Crescimento Necessário: +{m['crescimento_necessario']:.1f}%  |  Lucro Líquido na Meta: R$ {format_brl(m['lucro_na_meta'])}", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 8)
    pdf.set_text_color(107, 122, 112)
    pdf.cell(175, 4.5, f"Projeção mantendo estrutura atual e margem de contribuição de {m['margem_pct']}%.", ln=1)
    if cliente['ticket_medio'] > 0:
        pdf.set_x(19)
        pdf.set_font('helvetica', 'B', 8.5)
        pdf.set_text_color(27, 79, 114)
        conv_txt = f" | Leads/mês necessários: {m['leads_necessarios']}" if m['leads_necessarios'] > 0 else ""
        pdf.cell(175, 5, pdf_safe(f"Engenharia Comercial: {m['vendas_atuais']} vendas/mês atuais -> {m['vendas_meta']} vendas/mês na meta (+{m['novas_vendas']} novas vendas){conv_txt}"), ln=1)
    pdf.set_y(y + alt_meta + 6)

    # 5. Runway
    y = pdf.get_y()
    desenhar_card(y, 21, bg_color, bar_color)
    pdf.set_xy(19, y + 3)
    pdf.set_font('helvetica', 'B', 9)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 5, "FÔLEGO FINANCEIRO (RUNWAY DE CAIXA)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 9.5)
    pdf.set_text_color(40, 40, 40)
    if is_critical:
        texto_runway = f"ALERTA: O caixa atual (R$ {format_brl(cliente['caixa'])}) suporta apenas {m['meses_runway']:.1f} meses operando neste cenário de estresse."
    else:
        texto_runway = f"ESTÁVEL: A empresa possui margem suficiente para absorver a queda sem queimar o caixa (R$ {format_brl(cliente['caixa'])})."
    pdf.multi_cell(175, 5, texto_runway)
    pdf.set_y(y + 21 + 6)

    # 6. Prescrição Estratégica
    modelo = cliente.get('modelo', 'produtos')
    if modelo == 'servicos':
        acao_modelo = "Implantar confirmação ativa e lista de espera automatizada para zerar horários vagos."
    elif modelo == 'b2b':
        acao_modelo = "Estruturar cadência ativa de 30 contatos/dia e funil de recuperação de orçamentos parados."
    elif modelo == 'campo':
        acao_modelo = "Criar esteira de contratos de manutenção preventiva recorrente e roteirização de equipes."
    else:
        acao_modelo = "Treinar equipe de balcão/WhatsApp para venda de valor e blindagem da margem."

    txt_meta_vendas = f" (+{m['novas_vendas']} vendas/mês)" if m['novas_vendas'] > 0 else ""
    itens_prescricao = [
        ("1. REESTRUTURAÇÃO IMEDIATA: ", "Reduzir custos fixos não essenciais em pelo menos 15%."),
        ("2. INTELIGÊNCIA COMERCIAL: ", acao_modelo),
        ("3. PROTEÇÃO DE CAPITAL: ", "Congelar antecipações de recebíveis e renegociar prazos com fornecedores.")
    ] if is_critical else [
        ("1. EXPANSÃO ESTRATÉGICA: ", "Utilizar a resiliência do caixa para campanhas de aquisição de novos clientes."),
        ("2. BLINDAGEM DE MARGEM: ", acao_modelo),
        ("3. ESCALA DE VENDAS: ", f"Subir a régua de contatos diários focando em atingir a meta de R$ {format_brl(m['meta_fat'])}{txt_meta_vendas}.")
    ]

    pdf.set_font('helvetica', '', 9.5)
    altura_texto_presc = 0
    for tit, desc in itens_prescricao:
        linhas = max(1, math.ceil(pdf.get_string_width(tit + desc) / 170))
        altura_texto_presc += (linhas * 5.2) + 2.5
    altura_card_presc = 15 + altura_texto_presc

    y = pdf.get_y()
    desenhar_card(y, altura_card_presc, (15, 46, 28), (0, 200, 83))
    pdf.set_xy(19, y + 4.5)
    pdf.set_font('helvetica', 'B', 11)
    pdf.set_text_color(0, 200, 83)
    pdf.cell(175, 6, "PRESCRIÇÃO ESTRATÉGICA (O QUE FAZER AGORA?)", ln=1)

    pdf.set_left_margin(19)
    pdf.set_right_margin(16)
    pdf.set_y(y + 12.5)
    pdf.set_text_color(245, 248, 246)
    for tit, desc in itens_prescricao:
        pdf.set_x(19)
        pdf.set_font('helvetica', 'B', 9.5)
        pdf.write(5.2, pdf_safe(tit))
        pdf.set_font('helvetica', '', 9.5)
        pdf.write(5.2, pdf_safe(desc + "\n"))
        pdf.ln(2.2)

    pdf.set_left_margin(12)
    pdf.set_right_margin(12)

    # PÁGINA 2: RADAR DE MÉTRICAS CEGAS PERSONALIZADO
    pdf.add_page()
    y = pdf.get_y()
    altura_card_cegas = 98
    is_all_ok = m['qtd_cegas'] == 0

    pdf.set_fill_color(*( (240, 253, 244) if is_all_ok else (255, 245, 245) ))
    pdf.set_draw_color(*( (0, 200, 83) if is_all_ok else (220, 76, 62) ))
    pdf.set_line_width(0.5)
    pdf.rect(12, y, 186, altura_card_cegas, 'DF')
    pdf.set_fill_color(*( (0, 200, 83) if is_all_ok else (192, 57, 43) ))
    pdf.rect(12, y, 3.5, altura_card_cegas, 'F')

    pdf.set_xy(20, y + 5)
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(*( (15, 46, 28) if is_all_ok else (192, 57, 43) ))
    titulo_radar = "RADAR DE INDICADORES: 100% MONITORADO" if is_all_ok else f"ALERTA CRÍTICO: {m['qtd_cegas']} DE 4 MÉTRICAS CEGAS NA OPERAÇÃO"
    pdf.cell(172, 6.5, titulo_radar, ln=1)

    pdf.set_x(20)
    pdf.set_font('helvetica', '', 9.5)
    pdf.set_text_color(50, 50, 50)
    pdf.multi_cell(172, 5, "Raio-X de maturidade comercial e financeira levantado no seu diagnóstico:")
    pdf.ln(3)

    for item in m['radar_metricas']:
        y_item = pdf.get_y()
        ok_m = item['controlada']
        pdf.set_fill_color(255, 255, 255)
        pdf.set_draw_color(*( (183, 228, 199) if ok_m else (245, 183, 177) ))
        pdf.set_line_width(0.3)
        pdf.rect(20, y_item, 172, 13.5, 'DF')
        pdf.set_fill_color(*( (0, 200, 83) if ok_m else (192, 57, 43) ))
        pdf.rect(20, y_item, 2, 13.5, 'F')
        pdf.set_xy(24, y_item + 2)
        pdf.set_font('helvetica', 'B', 9.5)
        pdf.set_text_color(*( (15, 46, 28) if ok_m else (192, 57, 43) ))
        status_tag = "[CONTROLADO] " if ok_m else "[CEGO] "
        pdf.cell(165, 4.5, pdf_safe(status_tag + item['titulo']), ln=1)
        pdf.set_x(24)
        pdf.set_font('helvetica', '', 8.8)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(165, 4.5, pdf_safe(item['descricao']), ln=1)
        pdf.set_y(y_item + 15.5)

    pdf.set_x(20)
    pdf.set_font('helvetica', 'B', 9.5)
    pdf.set_text_color(*( (15, 46, 28) if is_all_ok else (146, 43, 33) ))
    rodape_radar = "Excelente visibilidade de dados. O foco agora é otimizar conversão e margem." if is_all_ok else "Operar sem esses números significa queimar margem todos os dias sem perceber."
    pdf.cell(172, 6, rodape_radar, ln=1)
    pdf.set_y(y + altura_card_cegas + 9)

    if is_critical:
        y_cons = pdf.get_y()
        desenhar_card(y_cons, 24, (253, 238, 217), (211, 84, 0))
        pdf.set_xy(19, y_cons + 3.5)
        pdf.set_font('helvetica', 'B', 10)
        pdf.set_text_color(160, 64, 0)
        pdf.cell(175, 5.5, "CONSEQUÊNCIA DA INAÇÃO", ln=1)
        pdf.set_x(19)
        pdf.set_font('helvetica', '', 9.2)
        pdf.set_text_color(50, 50, 50)
        pdf.multi_cell(175, 4.8, f"Se as medidas acima não forem aplicadas imediatamente, o capital de giro será consumido em {m['meses_runway']:.1f} meses, exigindo captação de crédito a juros predatórios.")
        pdf.set_y(y_cons + 24 + 10)

    y_btn = pdf.get_y()
    pdf.set_fill_color(37, 211, 102)
    pdf.set_font('helvetica', 'B', 11.5)
    pdf.set_text_color(255, 255, 255)
    link_wpp = f"https://wa.me/5581979091165?text=Olá,%20acabei%20de%20gerar%20meu%20laudo%20no%20Doutor%20Caixa%20e%20preciso%20de%20ajuda%20estratégica."
    pdf.set_xy(45, y_btn)
    pdf.cell(120, 13, "FALAR COM O DOUTOR CAIXA NO WHATSAPP", fill=True, align='C', link=link_wpp)

    pdf_bytes = bytearray(pdf.output())
    return send_file(io.BytesIO(pdf_bytes), download_name=f"Laudo_Doutor_Caixa_{cnpj}.pdf", as_attachment=True, mimetype='application/pdf')


if __name__ == '__main__':
    app.run(debug=True, port=5000)