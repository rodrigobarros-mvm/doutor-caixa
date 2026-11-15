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
WHATSAPP_API_URL = "".strip()
WHATSAPP_API_TOKEN = "".strip()
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
            vendas_30d INTEGER DEFAULT -1,
            qtd_vendedores INTEGER DEFAULT 1,
            receita_recorrente REAL DEFAULT 0,
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
    for col_sql in [
        "ALTER TABLE clientes_doutor_caixa ADD COLUMN vendas_30d INTEGER DEFAULT -1",
        "ALTER TABLE clientes_doutor_caixa ADD COLUMN qtd_vendedores INTEGER DEFAULT 1",
        "ALTER TABLE clientes_doutor_caixa ADD COLUMN receita_recorrente REAL DEFAULT 0"
    ]:
        try:
            c.execute(col_sql)
        except Exception:
            pass
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
        f"O Laudo Financeiro e Comercial da *{empresa}* já está pronto.\n\n"
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
        cegas.append("Custo por Cliente (CAC)")

    if dados.get("tem_ltv"):
        controladas.append(f"LTV: R$ {format_brl(dados['ltv'])}")
    else:
        cegas.append("Valor por Cliente (LTV)")

    if dados.get("tem_conversao"):
        controladas.append(f"Fechamento: {dados['taxa_conversao']}%")
    else:
        cegas.append("Taxa de Fechamento")

    if dados.get("tem_ciclo"):
        controladas.append(f"Prazos: {dados['ciclo_financeiro']} dias")
    else:
        cegas.append("Prazo de Pagamento/Recebimento")

    txt_controladas = ", ".join(controladas) if controladas else "Nenhuma (100% no escuro)"
    txt_cegas = ", ".join(cegas) if cegas else "Nenhuma (Operação monitorada)"

    tm = dados.get("ticket_medio", 0)
    fat = dados.get("fat", 0)
    meta = dados.get("meta_fat", 0)
    rec = float(dados.get("receita_recorrente", 0))
    v30 = int(dados.get("vendas_30d", -1))

    if tm > 0:
        if rec > 0:
            novas_vendas = max(0, math.ceil((meta - rec) / tm))
        elif v30 >= 0:
            novas_vendas = max(0, math.ceil(meta / tm) - v30)
        else:
            novas_vendas = max(0, math.ceil((meta - fat) / tm))
    else:
        novas_vendas = 0

    txt_rec = f"R$ {format_brl(rec)}/mês" if rec > 0 else "R$ 0,00 (Venda pontual)"

    mensagem = (
        f"🚨 <b>NOVO LEAD DOUTOR CAIXA!</b>\n\n"
        f"👤 <b>Lead:</b> {html.escape(str(dados.get('nome_pessoa', '')))} ({html.escape(str(dados.get('cargo', '')))})\n"
        f"🏢 <b>Empresa:</b> {html.escape(str(dados.get('nome', '')))} [{dados.get('modelo', '').upper()}]\n"
        f"📱 <b>WhatsApp:</b> https://wa.me/55{wpp_limpo}\n\n"
        f"💰 <b>Fat. Médio:</b> R$ {format_brl(fat)} | <b>Caixa:</b> R$ {format_brl(dados.get('caixa', 0))}\n"
        f"🔄 <b>Receita Recorrente/Retorno:</b> {txt_rec}\n"
        f"🎯 <b>Meta:</b> R$ {format_brl(meta)} | <b>Ticket:</b> R$ {format_brl(tm)} | <b>Gap:</b> +{novas_vendas} vendas/mês\n\n"
        f"🟢 <b>Sabe/Controla:</b> {html.escape(txt_controladas)}\n"
        f"🔴 <b>Pontos Cegos:</b> {html.escape(txt_cegas)}\n\n"
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

    v30_raw = row.get("vendas_30d")
    vendas_30d = int(v30_raw) if v30_raw is not None and str(v30_raw) != "" else -1
    modelo = row.get("modelo") or "produtos"
    rec = float(row.get("receita_recorrente") or 0.0)
    if modelo == "produtos":
        rec = 0.0
        vendas_30d = -1

    return {
        "cnpj": str(row.get("cnpj", "")),
        "nome": row.get("nome", "Empresa"),
        "ativo": bool(row.get("ativo", True)),
        "caixa": float(row.get("caixa") or 0.0),
        "fat": float(row.get("fat") or 0.0),
        "fixo": float(row.get("fixo") or 0.0),
        "margem": margem_val,
        "modelo": modelo,
        "meta_fat": float(row.get("meta_fat") or (float(row.get("fat") or 0.0) * 1.3)),
        "ticket_medio": float(row.get("ticket_medio") or 0.0),
        "vendas_30d": vendas_30d,
        "qtd_vendedores": max(1, int(row.get("qtd_vendedores") or 1)),
        "receita_recorrente": rec,
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

    ok, dados = supabase_rest("GET", f"clientes_doutor_caixa?cnpj=eq.{cnpj_limpo}&select=*")
    if ok and isinstance(dados, list) and len(dados) > 0:
        return normalizar_cliente(dados[0])

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
            "vendas_30d": -1,
            "qtd_vendedores": 1,
            "receita_recorrente": 0.0,
            "tem_cac": False,
            "tem_ltv": False,
            "tem_conversao": True,
            "taxa_conversao": 25.0,
            "tem_ciclo": False
        })
    return None


def salvar_cliente_db(registro):
    cnpj_limpo = registro["cnpj"]

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
        historico = historico[-5:]

    registro["historico_json"] = json.dumps(historico, ensure_ascii=False)
    registro["atualizado_em"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn = sqlite3.connect(DB_LOCAL_PATH)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO clientes_doutor_caixa (
                cnpj, nome, ativo, caixa, fat, fixo, margem, modelo, meta_fat,
                ticket_medio, vendas_30d, qtd_vendedores, receita_recorrente,
                tem_cac, cac, tem_ltv, ltv, tem_conversao, taxa_conversao,
                tem_ciclo, ciclo_financeiro, nome_pessoa, cargo, whatsapp,
                historico_json, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            cnpj_limpo, registro["nome"], 1, registro["caixa"], registro["fat"],
            registro["fixo"], registro["margem"], registro["modelo"], registro["meta_fat"],
            registro["ticket_medio"], registro["vendas_30d"], registro["qtd_vendedores"],
            registro["receita_recorrente"], int(registro["tem_cac"]), registro["cac"],
            int(registro["tem_ltv"]), registro["ltv"], int(registro["tem_conversao"]),
            registro["taxa_conversao"], int(registro["tem_ciclo"]),
            registro["ciclo_financeiro"], registro["nome_pessoa"], registro["cargo"],
            registro["whatsapp"], registro["historico_json"], registro["atualizado_em"]
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"ERRO GRAVAÇÃO SQLITE: {e}")

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
        "vendas_30d": registro["vendas_30d"],
        "qtd_vendedores": registro["qtd_vendedores"],
        "receita_recorrente": registro["receita_recorrente"],
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
        <h2>Diagnóstico Técnico - Doutor Caixa v5.6</h2>
        <p><b>1. Banco Local (SQLite):</b> ATIVO ({qtd_local} registros salvos)</p>
        <p><b>2. DNS Supabase:</b> {dns_status}</p>
        <p><b>3. Sincronização Supabase:</b> {status_sb}</p>
        <p><b>4. Disparo WhatsApp API:</b> {'CONFIGURADO' if WHATSAPP_API_URL else 'Modo Manual (Link Direto Ativo)'}</p>
        <hr>
        <p><a href="/">Voltar para a Home</a></p>
    </div>
    """


# --- TEMPLATES HTML ---
TEMPLATE_HOME = r"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa | Diagnóstico Financeiro e Comercial</title>
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
        .footer-seal { margin-top: 24px; padding-top: 16px; border-top: 1px solid #eef4f0; font-size: 11px; color: #7c8b82; line-height: 1.5; }
        .footer-seal strong { color: #0F2E1C; }
        @media (max-width: 480px) { body { background: #FFFFFF; padding: 0; align-items: flex-start; } .login-box { box-shadow: none; border-radius: 0; padding: 32px 20px; max-width: 100%; } }
    </style>
</head>
<body>
    <div class="login-box">
        <img src="/static/logo.png" alt="Doutor Caixa Logo" class="logo">
        <h1>Raio-X do Seu Caixa e das Suas Vendas</h1>
        <p class="subtitle">Descubra em 2 minutos quanto tempo sua empresa aguenta se as vendas caírem 30% e receba um plano prático para vender mais e proteger seu lucro.</p>
        
        <a href="/diagnostico" class="btn-primary">🚀 Fazer Meu Diagnóstico Gratuito</a>
        <a href="https://wa.me/5581979091165?text=Olá!%20Vim%20pelo%20Doutor%20Caixa%20e%20gostaria%20de%20conversar%20sobre%20o%20caixa%20e%20as%20vendas%20da%20minha%20empresa." target="_blank" class="btn-wpp-home">💬 Falar no WhatsApp</a>

        <div class="divider">Já possui laudo?</div>

        {% if erro %}
            <div class="erro-msg">{{ erro }}</div>
        {% endif %}

        <form method="POST" action="/acessar">
            <input type="text" name="cnpj" inputmode="numeric" placeholder="Digite seu CNPJ (somente números)" required>
            <button type="submit" class="btn-secondary">Acessar Laudo Emitido</button>
        </form>

        <div class="footer-seal">
            🔒 Dados protegidos com sigilo total (LGPD).<br>
            Doutor Caixa é uma empresa da <strong>MaqTrak</strong> - Hub de Soluções em Inteligência de Mercado.
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_SUCESSO = r"""
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
        <h1>✅ Laudo Gerado com Sucesso!</h1>
        <p>Analisamos todos os números da sua empresa e preparamos o seu plano de ação completo.</p>
        
        <div class="alert-box">
            <strong>Fique atento ao seu WhatsApp!</strong>
            <span>O link exclusivo para abrir seu Laudo Financeiro na tela e baixar o PDF será enviado em instantes para:<br><br><b>{{ whatsapp }}</b></span>
        </div>

        <a href="/" class="btn">Voltar para a Tela Inicial</a>
    </div>
</body>
</html>
"""

TEMPLATE_DIAGNOSTICO = r"""
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
        .form-container { max-width: 600px; margin: 0 auto; background: #FFFFFF; padding: 30px 32px; border-radius: 16px; box-shadow: 0 8px 28px rgba(15, 46, 28, 0.08); }
        .top-bar { display: flex; align-items: center; justify-content: space-between; border-bottom: 2px solid #E8F7EE; padding-bottom: 14px; margin-bottom: 18px; }
        .logo { max-width: 115px; }
        .back-link { color: #6B7A70; text-decoration: none; font-size: 13px; font-weight: 600; }
        .back-link:hover { color: #0F2E1C; }

        /* Barra de Progresso do Wizard */
        .wizard-progress { margin-bottom: 22px; }
        .progress-meta { display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-weight: 700; color: #0F2E1C; margin-bottom: 6px; }
        .progress-meta span.step-tag { color: #00C853; text-transform: uppercase; letter-spacing: 0.4px; }
        .progress-track { width: 100%; height: 8px; background: #E8F7EE; border-radius: 99px; overflow: hidden; }
        .progress-fill { height: 100%; width: 25%; background: #00C853; border-radius: 99px; transition: width 0.35s ease; }

        .step-pane { display: none; animation: fadeInStep 0.28s ease; }
        .step-pane.active { display: block; }
        @keyframes fadeInStep {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }

        h2 { margin: 0 0 6px 0; font-size: 20px; color: #0F2E1C; }
        .desc { margin: 0 0 20px 0; font-size: 13.5px; color: #6B7A70; line-height: 1.45; }
        
        .field-group { margin-bottom: 16px; }
        label { display: block; font-size: 13px; font-weight: 700; color: #0F2E1C; margin-bottom: 4px; }
        .hint { display: block; font-size: 11.5px; color: #6B7A70; margin-bottom: 6px; line-height: 1.35; }
        input[type="text"], input[type="tel"], input[type="number"], select { width: 100%; padding: 13px 14px; border: 2px solid #E8F7EE; border-radius: 8px; font-family: 'Poppins', sans-serif; font-size: 14.5px; color: #0F2E1C; outline: none; background: #FFFFFF; transition: 0.2s; }
        input:focus, select:focus { border-color: #00C853; }
        .row-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }

        .wpp-box { background: #fff9e6; border: 1.5px solid #f39c12; padding: 14px; border-radius: 10px; margin-bottom: 16px; }
        .wpp-box label { color: #d35400; }
        .wpp-box .hint-alert { font-size: 11.5px; color: #b9770e; font-weight: 600; margin-bottom: 8px; display: block; line-height: 1.4; }
        .wpp-box input { border-color: #f5b041; }
        .wpp-box input:focus { border-color: #d35400; }

        .rec-box { background: #f0fdf4; border: 1.5px solid #a3e4bd; border-radius: 10px; padding: 14px; margin-bottom: 16px; }
        .rec-note { background: #f4f8f6; border: 1px solid #dfece5; border-radius: 8px; padding: 11px 14px; font-size: 12px; color: #4e6156; margin-bottom: 16px; line-height: 1.45; }

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

        .nav-buttons { display: flex; gap: 12px; margin-top: 22px; }
        .btn-prev { background: #f0f5f2; color: #0F2E1C; border: 1.5px solid #cfe0d6; padding: 16px 20px; border-radius: 10px; font-family: 'Poppins', sans-serif; font-size: 15px; font-weight: 700; cursor: pointer; flex: 1; transition: 0.2s; }
        .btn-prev:hover { background: #e1ece6; }
        .btn-next { background: #00C853; color: #FFFFFF; border: none; padding: 16px 22px; border-radius: 10px; font-family: 'Poppins', sans-serif; font-size: 15.5px; font-weight: 700; cursor: pointer; flex: 2; box-shadow: 0 4px 12px rgba(0, 200, 83, 0.25); transition: 0.2s; }
        .btn-next:hover { background: #00a645; }

        .sigilo-box { margin-top: 18px; background: #f7faf8; padding: 12px; border-radius: 8px; font-size: 11px; color: #6B7A70; text-align: center; line-height: 1.45; }
        .brand-footer { margin-top: 7px; padding-top: 7px; border-top: 1px solid #e3ece7; font-size: 10.5px; color: #5f6f65; }
        .brand-footer strong { color: #0F2E1C; }

        @media (max-width: 540px) {
            body { background: #FFFFFF; padding: 0; }
            .form-container { box-shadow: none; border-radius: 0; padding: 20px 16px 36px 16px; max-width: 100%; }
            .row-2 { grid-template-columns: 1fr; gap: 0; }
            .nav-buttons { flex-direction: column-reverse; }
            .btn-prev, .btn-next { width: 100%; flex: none; }
        }
    </style>
</head>
<body>
    <div class="form-container">
        <div class="top-bar">
            <img src="/static/logo.png" alt="Doutor Caixa" class="logo">
            <a href="/" class="back-link">✕ Sair</a>
        </div>

        <div class="wizard-progress">
            <div class="progress-meta">
                <span class="step-tag" id="step_label_title">Etapa 1 de 4 — Dados da Empresa</span>
                <span id="step_pct">25%</span>
            </div>
            <div class="progress-track">
                <div class="progress-fill" id="progress_fill"></div>
            </div>
        </div>

        <form method="POST" action="/diagnostico" id="form_diagnostico" onsubmit="return validarEtapa4()">
            
            <!-- ETAPA 1: DADOS DA EMPRESA -->
            <div class="step-pane active" id="step_1">
                <h2>1. Dados da Empresa</h2>
                <p class="desc">Conte-nos qual é o seu negócio para calibrarmos o diagnóstico ao seu setor.</p>

                <div class="field-group">
                    <label>Nome da Empresa</label>
                    <input type="text" name="nome" id="empresa_nome" placeholder="Ex: Distribuidora Recife Ltda">
                </div>

                <div class="field-group">
                    <label>CNPJ Válido (Somente números)</label>
                    <input type="text" name="cnpj" id="cnpj" inputmode="numeric" maxlength="18" placeholder="00.000.000/0000-00">
                </div>

                <div class="field-group">
                    <label>Ramo de Atuação / Modelo de Venda</label>
                    <select name="modelo" id="modelo_select" onchange="atualizarModeloNegocio()">
                        <option value="produtos">Comércio / Varejo / Distribuição (Produtos)</option>
                        <option value="servicos">Clínicas / Consultórios / Serviços por Agenda</option>
                        <option value="b2b">Consultoria / Serviços B2B / Contratos</option>
                        <option value="campo">Manutenção / Assistência Técnica / Serviços de Campo</option>
                    </select>
                </div>

                <div id="rec_note_varejo" class="rec-note">
                    🛒 <b>Comércio e Varejo:</b> Como cada mês começa sem contratos fixos garantidos, nosso cálculo vai focar em <b>giro de estoque, movimento diário de loja/WhatsApp e proteção da margem</b>.
                </div>

                <div id="rec_box_b2b" class="rec-box" style="display: none;">
                    <label>Receita Mensal Já Garantida em Contratos (R$)</label>
                    <span class="hint">Soma das mensalidades ativas hoje (coloque 0 se você vende apenas projetos avulsos)</span>
                    <input type="text" name="receita_recorrente_rs" id="input_rec_rs" class="moeda" inputmode="numeric" placeholder="Ex: 20.000,00">
                </div>

                <div id="rec_box_servicos" class="rec-box" style="display: none;">
                    <label>% do Faturamento vindo de Retorno de Pacientes/Clientes</label>
                    <span class="hint">Clínicas e serviços recorrentes costumam ter de <b>40% a 80%</b> dos clientes retornando a cada 3 ou 6 meses</span>
                    <input type="number" step="1" min="0" max="100" name="pct_recorrencia" id="input_rec_pct" inputmode="numeric" placeholder="Ex: 50">
                </div>

                <div class="nav-buttons">
                    <button type="button" class="btn-next" onclick="irParaEtapa(2)">Avançar →</button>
                </div>
            </div>

            <!-- ETAPA 2: DADOS FINANCEIROS & COMERCIAIS -->
            <div class="step-pane" id="step_2">
                <h2>2. Dados Financeiros & Comerciais</h2>
                <p class="desc">Use valores aproximados da sua média mensal. Não precisa ser exato nos centavos.</p>

                <div class="row-2">
                    <div class="field-group">
                        <label>Dinheiro em Caixa Hoje (R$)</label>
                        <span class="hint">Saldo disponível na conta + espécie</span>
                        <input type="text" name="caixa" id="inp_caixa" class="moeda" inputmode="numeric" placeholder="120.000,00">
                    </div>

                    <div class="field-group">
                        <label>Faturamento Médio Mensal (R$)</label>
                        <span class="hint">Total que entra de vendas por mês</span>
                        <input type="text" name="fat" id="inp_fat" class="moeda" inputmode="numeric" placeholder="300.000,00">
                    </div>
                </div>

                <div class="row-2">
                    <div class="field-group">
                        <label>Despesas Fixas Mensais (R$)</label>
                        <span class="hint">Aluguel, folha, energia, sistemas</span>
                        <input type="text" name="fixo" id="inp_fixo" class="moeda" inputmode="numeric" placeholder="95.000,00">
                    </div>

                    <div class="field-group">
                        <label>Margem que Sobra por Venda (%)</label>
                        <span class="hint">O que sobra após pagar produto/imposto/comissão</span>
                        <input type="number" step="0.1" min="1" max="100" name="margem" id="inp_margem" inputmode="decimal" placeholder="Ex: 38">
                    </div>
                </div>

                <div class="row-2">
                    <div class="field-group">
                        <label>Valor Médio por Venda (R$)</label>
                        <span class="hint">Ticket médio de cada venda ou contrato</span>
                        <input type="text" name="ticket_medio" id="inp_ticket" class="moeda" inputmode="numeric" placeholder="2.500,00">
                    </div>

                    <div class="field-group">
                        <label>Meta de Faturamento Mensal (R$)</label>
                        <span class="hint">Quanto você quer faturar por mês</span>
                        <input type="text" name="meta_fat" id="inp_meta" class="moeda" inputmode="numeric" placeholder="450.000,00">
                    </div>
                </div>

                <div class="row-2" id="box_equipe_vendas">
                    <div class="field-group">
                        <label>Novas Vendas nos Últimos 30 Dias</label>
                        <span class="hint">Opcional (coloque <b>0</b> se não fechou nada novo)</span>
                        <input type="number" step="1" min="0" name="vendas_30d" id="inp_vendas_30d" inputmode="numeric" placeholder="Ex: 0, 2, 15...">
                    </div>

                    <div class="field-group">
                        <label>Pessoas na Equipe Comercial</label>
                        <span class="hint">Quantas pessoas atendem ou vendem hoje</span>
                        <input type="number" step="1" min="1" name="qtd_vendedores" id="inp_vendedores" inputmode="numeric" value="1">
                    </div>
                </div>

                <div class="nav-buttons">
                    <button type="button" class="btn-prev" onclick="irParaEtapa(1)">← Voltar</button>
                    <button type="button" class="btn-next" onclick="irParaEtapa(3)">Avançar →</button>
                </div>
            </div>

            <!-- ETAPA 3: RADAR DE INDICADORES (MÉTRICAS CEGAS) -->
            <div class="step-pane" id="step_3">
                <h2>3. Radar de Indicadores</h2>
                <p class="desc">Ative a chave <b>apenas</b> para os números que você realmente acompanha hoje. Se não souber, deixe desligado — isso ajuda a identificar pontos cegos.</p>

                <div class="metric-card" id="card_cac">
                    <label class="metric-header" for="toggle_cac">
                        <div class="metric-info">
                            <strong>Sei quanto custa trazer 1 cliente novo (CAC)</strong>
                            <span>Total gasto com anúncios e vendas dividido pelos novos clientes</span>
                        </div>
                        <div class="switch">
                            <input type="checkbox" id="toggle_cac" name="tem_cac" onchange="toggleMetrica('cac')">
                            <span class="slider"></span>
                        </div>
                    </label>
                    <div class="metric-input-box" id="box_cac">
                        <label>Custo médio por cliente conquistado (R$)</label>
                        <input type="text" name="cac" id="input_cac" class="moeda" inputmode="numeric" placeholder="Ex: 350,00">
                    </div>
                </div>

                <div class="metric-card" id="card_ltv">
                    <label class="metric-header" for="toggle_ltv">
                        <div class="metric-info">
                            <strong>Sei quanto cada cliente gasta ao longo do tempo (LTV)</strong>
                            <span>Soma total que um cliente deixa na empresa enquanto compra de você</span>
                        </div>
                        <div class="switch">
                            <input type="checkbox" id="toggle_ltv" name="tem_ltv" onchange="toggleMetrica('ltv')">
                            <span class="slider"></span>
                        </div>
                    </label>
                    <div class="metric-input-box" id="box_ltv">
                        <label>Valor médio total por cliente (R$)</label>
                        <input type="text" name="ltv" id="input_ltv" class="moeda" inputmode="numeric" placeholder="Ex: 4.800,00">
                    </div>
                </div>

                <div class="metric-card" id="card_conv">
                    <label class="metric-header" for="toggle_conv">
                        <div class="metric-info">
                            <strong>Sei quantos orçamentos viram venda (%)</strong>
                            <span>De cada 100 pessoas atendidas ou orçadas, quantas fecham</span>
                        </div>
                        <div class="switch">
                            <input type="checkbox" id="toggle_conv" name="tem_conversao" onchange="toggleMetrica('conv')">
                            <span class="slider"></span>
                        </div>
                    </label>
                    <div class="metric-input-box" id="box_conv">
                        <label>Percentual de fechamento (%)</label>
                        <input type="number" step="0.1" min="0.1" max="100" name="taxa_conversao" id="input_conv" inputmode="decimal" placeholder="Ex: 20">
                    </div>
                </div>

                <div class="metric-card" id="card_ciclo">
                    <label class="metric-header" for="toggle_ciclo">
                        <div class="metric-info">
                            <strong>Sei o prazo entre pagar fornecedores e receber (Dias)</strong>
                            <span>Diferença de dias entre o dinheiro sair para compras e voltar nas vendas</span>
                        </div>
                        <div class="switch">
                            <input type="checkbox" id="toggle_ciclo" name="tem_ciclo" onchange="toggleMetrica('ciclo')">
                            <span class="slider"></span>
                        </div>
                    </label>
                    <div class="metric-input-box" id="box_ciclo">
                        <label>Diferença de prazo em dias</label>
                        <input type="number" step="1" name="ciclo_financeiro" id="input_ciclo" inputmode="numeric" placeholder="Ex: 35">
                    </div>
                </div>

                <div class="nav-buttons">
                    <button type="button" class="btn-prev" onclick="irParaEtapa(2)">← Voltar</button>
                    <button type="button" class="btn-next" onclick="irParaEtapa(4)">Avançar →</button>
                </div>
            </div>

            <!-- ETAPA 4: DADOS DO SOLICITANTE -->
            <div class="step-pane" id="step_4">
                <h2>4. Dados do Solicitante</h2>
                <p class="desc">Tudo pronto! Informe seus dados para enviarmos o link exclusivo do seu laudo completo.</p>

                <div class="row-2">
                    <div class="field-group">
                        <label>Seu Nome</label>
                        <input type="text" name="nome_pessoa" id="inp_nome_pessoa" placeholder="Ex: Rodrigo Barros">
                    </div>
                    <div class="field-group">
                        <label>Seu Cargo</label>
                        <select name="cargo" id="inp_cargo">
                            <option value="" disabled selected>Selecione...</option>
                            <option value="Sócio / Proprietário / Diretor">Sócio / Proprietário / Diretor</option>
                            <option value="Gerente Comercial / Vendas">Gerente Comercial / Vendas</option>
                            <option value="Gerente Financeiro">Gerente Financeiro</option>
                            <option value="Outros">Outros</option>
                        </select>
                    </div>
                </div>

                <div class="wpp-box">
                    <label>Seu WhatsApp com DDD</label>
                    <span class="hint-alert">⚠️ Importante: O link para visualizar seu laudo e baixar o PDF será enviado EXCLUSIVAMENTE para este número.</span>
                    <input type="tel" name="whatsapp" id="whatsapp" placeholder="(81) 99999-9999">
                </div>

                <div class="nav-buttons">
                    <button type="button" class="btn-prev" onclick="irParaEtapa(3)">← Voltar</button>
                    <button type="submit" class="btn-next">📊 Receber Meu Laudo Financeiro</button>
                </div>
            </div>

        </form>

        <div class="sigilo-box">
            🔒 <strong>Sigilo Garantido:</strong> Seus dados são confidenciais e protegidos pela LGPD.
            <div class="brand-footer">Doutor Caixa é uma empresa da <strong>MaqTrak</strong> - Hub de Soluções em Inteligência de Mercado.</div>
        </div>
    </div>

    <script>
        const titulosEtapas = {
            1: "Etapa 1 de 4 — Dados da Empresa",
            2: "Etapa 2 de 4 — Financeiro & Vendas",
            3: "Etapa 3 de 4 — Radar de Indicadores",
            4: "Etapa 4 de 4 — Envio do Laudo"
        };

        function parseMoedaJS(val) {
            if (!val) return 0;
            let limpo = val.replace(/\./g, '').replace(',', '.').replace(/[^\d.]/g, '');
            return parseFloat(limpo) || 0;
        }

        function validarCNPJ(cnpj) {
            cnpj = cnpj.replace(/[^\d]+/g,'');
            if(cnpj == '') return false;
            if (cnpj.length != 14) return false;
            if (/^(\d)\1+$/.test(cnpj)) return false;
            let tamanho = cnpj.length - 2;
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

        function validarEtapaAtual(etapaAtual) {
            if (etapaAtual === 1) {
                let emp = document.getElementById('empresa_nome');
                if (!emp.value.trim()) {
                    alert("Por favor, informe o nome da empresa.");
                    emp.focus();
                    return false;
                }
                let cnpjInput = document.getElementById('cnpj');
                if (!validarCNPJ(cnpjInput.value)) {
                    alert("O CNPJ informado é inválido. Por favor, confira os números.");
                    cnpjInput.focus();
                    return false;
                }
            }
            if (etapaAtual === 2) {
                let caixa = document.getElementById('inp_caixa');
                let fat = document.getElementById('inp_fat');
                let fixo = document.getElementById('inp_fixo');
                let margem = document.getElementById('inp_margem');
                let ticket = document.getElementById('inp_ticket');
                let meta = document.getElementById('inp_meta');

                if (!caixa.value.trim()) { alert("Informe o dinheiro em caixa hoje."); caixa.focus(); return false; }
                if (parseMoedaJS(fat.value) <= 0) { alert("Informe o faturamento médio mensal."); fat.focus(); return false; }
                if (parseMoedaJS(fixo.value) <= 0) { alert("Informe as despesas fixas mensais."); fixo.focus(); return false; }
                let mVal = parseFloat(margem.value);
                if (!mVal || mVal <= 0 || mVal > 100) { alert("Informe a margem que sobra por venda (entre 1% e 100%)."); margem.focus(); return false; }
                if (parseMoedaJS(ticket.value) <= 0) { alert("Informe o valor médio por venda."); ticket.focus(); return false; }
                if (parseMoedaJS(meta.value) <= 0) { alert("Informe a meta de faturamento mensal."); meta.focus(); return false; }
            }
            if (etapaAtual === 3) {
                const keys = ['cac', 'ltv', 'conv', 'ciclo'];
                for (let k of keys) {
                    let chk = document.getElementById('toggle_' + k);
                    let inp = document.getElementById('input_' + k);
                    if (chk.checked && !inp.value.trim()) {
                        alert("Você ativou um indicador. Preencha o valor dele ou desative a chave.");
                        inp.focus();
                        return false;
                    }
                }
            }
            return true;
        }

        function irParaEtapa(destino) {
            let ativa = document.querySelector('.step-pane.active');
            let atual = parseInt(ativa.id.replace('step_', ''));

            if (destino > atual && !validarEtapaAtual(atual)) {
                return;
            }

            document.querySelectorAll('.step-pane').forEach(el => el.classList.remove('active'));
            document.getElementById('step_' + destino).classList.add('active');

            document.getElementById('step_label_title').innerText = titulosEtapas[destino];
            let pct = destino * 25;
            document.getElementById('step_pct').innerText = pct + '%';
            document.getElementById('progress_fill').style.width = pct + '%';

            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        function validarEtapa4() {
            let nomeP = document.getElementById('inp_nome_pessoa');
            let cargo = document.getElementById('inp_cargo');
            let wppInput = document.getElementById('whatsapp');

            if (!nomeP.value.trim()) {
                alert("Por favor, informe o seu nome.");
                nomeP.focus();
                return false;
            }
            if (!cargo.value) {
                alert("Por favor, selecione o seu cargo.");
                cargo.focus();
                return false;
            }
            let wpp = wppInput.value.replace(/\D/g, '');
            let regexCelularBR = /^[1-9]{2}9\d{8}$/;
            if (!regexCelularBR.test(wpp)) {
                alert("Por favor, insira um número de WhatsApp válido com DDD (ex: 81 99999-9999).");
                wppInput.focus();
                return false;
            }
            return true;
        }

        function atualizarModeloNegocio() {
            const mod = document.getElementById('modelo_select').value;
            const noteVarejo = document.getElementById('rec_note_varejo');
            const boxB2B = document.getElementById('rec_box_b2b');
            const boxServ = document.getElementById('rec_box_servicos');
            const boxEquipe = document.getElementById('box_equipe_vendas');

            noteVarejo.style.display = 'none';
            boxB2B.style.display = 'none';
            boxServ.style.display = 'none';

            if (mod === 'produtos') {
                noteVarejo.style.display = 'block';
                boxEquipe.style.display = 'none';
            } else if (mod === 'servicos') {
                boxServ.style.display = 'block';
                boxEquipe.style.display = 'grid';
            } else {
                boxB2B.style.display = 'block';
                boxEquipe.style.display = 'grid';
            }
        }

        function toggleMetrica(key) {
            const chk = document.getElementById('toggle_' + key);
            const box = document.getElementById('box_' + key);
            const card = document.getElementById('card_' + key);
            const inp = document.getElementById('input_' + key);
            if (chk.checked) {
                box.classList.add('visible');
                card.classList.add('active');
                inp.focus();
            } else {
                box.classList.remove('visible');
                card.classList.remove('active');
                inp.value = '';
            }
        }

        document.getElementById('cnpj').addEventListener('input', function (e) {
            let v = e.target.value.replace(/\D/g, '').slice(0, 14);
            v = v.replace(/^(\d{2})(\d)/, '$1.$2');
            v = v.replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3');
            v = v.replace(/\.(\d{3})(\d)/, '.$1/$2');
            v = v.replace(/(\d{4})(\d)/, '$1-$2');
            e.target.value = v;
        });

        document.getElementById('whatsapp').addEventListener('input', function (e) {
            let x = e.target.value.replace(/\D/g, '').match(/(\d{0,2})(\d{0,5})(\d{0,4})/);
            e.target.value = !x[2] ? x[1] : '(' + x[1] + ') ' + x[2] + (x[3] ? '-' + x[3] : '');
        });

        document.querySelectorAll('.moeda').forEach(function(input) {
            input.addEventListener('input', function(e) {
                let v = e.target.value.replace(/\D/g, '');
                if (!v) { e.target.value = ''; return; }
                v = (parseInt(v, 10) / 100).toFixed(2) + '';
                v = v.replace('.', ',');
                v = v.replace(/(\d)(?=(\d{3})+(?!\d))/g, '$1.');
                e.target.value = v;
            });
        });

        atualizarModeloNegocio();
    </script>
</body>
</html>
"""

TEMPLATE_DASHBOARD = r"""
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
        .paciente-box { background: #f7faf8; padding: 14px 18px; border-radius: 8px; margin-bottom: 14px; border-left: 5px solid var(--verde-profundo); }
        .paciente-box p { margin: 0; font-size: 16px; color: var(--cinza-neutro); }
        .paciente-box strong { color: var(--verde-profundo); }
        .paciente-box small { display: block; margin-top: 2px; font-size: 13px; color: var(--cinza-neutro); }
        
        .premissas-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 18px; }
        .prem-item { background: #f4f8f6; border: 1px solid #dfece5; border-radius: 8px; padding: 10px 12px; }
        .prem-item span { display: block; font-size: 11px; color: #6B7A70; font-weight: 600; text-transform: uppercase; }
        .prem-item strong { display: block; font-size: 14px; color: #0F2E1C; margin-top: 2px; }

        .hist-box { background: #eef9f2; border: 1.5px solid #00C853; border-radius: 8px; padding: 12px 16px; margin-bottom: 18px; font-size: 13.5px; color: #0F2E1C; }
        .card { background: var(--menta-suave); padding: 18px 20px; border-radius: 10px; margin-bottom: 14px; border-left: 5px solid var(--verde-caixa); }
        .card-label { color: var(--cinza-neutro); font-weight: 700; font-size: 14px; }
        .alert-red { border-left-color: var(--cor-alerta-texto); background: var(--cor-alerta-fundo); }
        .alert-green { border-left-color: var(--verde-caixa); background: var(--menta-suave); }
        .alert-blue { border-left-color: var(--azul-metrica); background: var(--azul-fundo); }
        .value { font-size: 26px; font-weight: 700; color: var(--verde-profundo); margin-top: 4px; }
        .value.red { color: var(--cor-alerta-texto); }
        .value.blue { color: var(--azul-metrica); }
        
        .explain-box { background: rgba(255, 255, 255, 0.78); border-radius: 7px; padding: 10px 13px; margin-top: 10px; font-size: 12.8px; color: #2c3e50; line-height: 1.5; border: 1px solid rgba(0,0,0,0.06); }
        .explain-box b { color: #0F2E1C; }
        .alerta-meta-pe { background: #fdecea; border: 1.5px solid #e74c3c; color: #922b21; border-radius: 7px; padding: 10px 13px; margin-top: 10px; font-size: 12.8px; line-height: 1.45; }
        .alerta-capacidade { background: #fff8e1; border: 1.5px solid #f39c12; color: #7e5109; border-radius: 7px; padding: 9px 12px; margin-top: 8px; font-size: 12.5px; line-height: 1.45; }
        .engenharia-box { background: #ffffff; border: 1px solid #bcd9ea; border-radius: 8px; padding: 13px 15px; margin-top: 10px; font-size: 13px; color: #1b4f72; line-height: 1.55; }
        
        .prescricao-card { background: var(--verde-profundo); border-left: 5px solid var(--verde-caixa); color: var(--branco); padding: 22px 20px; border-radius: 10px; margin-bottom: 16px; }
        .prescricao-title { color: var(--verde-caixa); font-size: 16px; font-weight: 700; margin-bottom: 14px; letter-spacing: 0.3px; }
        .lista-acoes p { margin: 0 0 13px 0; color: #f0f4f1; font-size: 14.5px; line-height: 1.55; }
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
        .dash-footer { margin-top: 24px; padding-top: 14px; border-top: 1px solid #e6efe9; text-align: center; font-size: 11px; color: #7c8b82; }
        .dash-footer strong { color: #0F2E1C; }
        @media (max-width: 640px) {
            body { padding: 0; background: var(--branco); }
            .container { max-width: 100%; border-radius: 0; box-shadow: none; padding: 20px 16px 32px 16px; }
            .header { flex-direction: row; align-items: center; padding-bottom: 14px; margin-bottom: 18px; }
            .logo { max-width: 110px; }
            .header h1 { font-size: 18px; }
            .header span { font-size: 10px; }
            .premissas-grid { grid-template-columns: 1fr 1fr; }
            .card { padding: 15px 16px; margin-bottom: 12px; }
            .card-label { font-size: 13px; }
            .value { font-size: 22px; }
            .mc-grid { grid-template-columns: 1fr; }
            .metricas-cegas-card { padding: 16px; }
            .mc-title { font-size: 16px; }
            .botoes { flex-direction: column; gap: 10px; }
            .btn { width: 100%; min-width: 100%; padding: 16px; font-size: 15px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="/static/logo.png" alt="Doutor Caixa Logo" class="logo">
            <div class="header-titles">
                <span>Diagnóstico Financeiro e Comercial</span>
                <h1>Laudo da Operação</h1>
            </div>
        </div>
        
        <div class="paciente-box">
            <p>Empresa Analisada: <strong>{{ cliente.nome }}</strong></p>
            <small>CNPJ: {{ cnpj|format_cnpj }} | Ramo: <strong>{{ nome_motor_comercial }}</strong>{% if cliente.ticket_medio > 0 %} | Valor Médio por Venda: <strong>R$ {{ cliente.ticket_medio|format_brl }}</strong>{% endif %}{% if cliente.modelo != 'produtos' %} | Equipe Comercial: <strong>{{ qtd_vendedores }}</strong>{% endif %}</small>
        </div>

        <div class="premissas-grid">
            <div class="prem-item">
                <span>Faturamento Médio</span>
                <strong>R$ {{ cliente.fat|format_brl }}</strong>
            </div>
            <div class="prem-item">
                <span>Receita Garantida</span>
                <strong>{% if receita_recorrente > 0 %}R$ {{ receita_recorrente|format_brl }}{% else %}R$ 0,00 (0%){% endif %}</strong>
            </div>
            <div class="prem-item">
                <span>Despesa Fixa</span>
                <strong>R$ {{ cliente.fixo|format_brl }}</strong>
            </div>
            <div class="prem-item">
                <span>Sobra / Caixa Hoje</span>
                <strong>{{ "%.0f"|format(margem_pct) }}% / R$ {{ cliente.caixa|format_brl }}</strong>
            </div>
        </div>

        {% if comparativo %}
        <div class="hist-box">
            📈 <strong>Evolução desde a Última Análise ({{ comparativo.data }}):</strong><br>
            Dinheiro em Caixa: <strong>{{ comparativo.diff_caixa }}</strong> | Faturamento: <strong>{{ comparativo.diff_fat }}</strong>
        </div>
        {% endif %}

        <!-- 0. FOTOGRAFIA ATUAL -->
        <div class="card {% if lucro_atual < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div class="card-label">0. Resultado Atual (Quanto Sobra ou Falta Hoje por Mês)</div>
            <div class="value {% if lucro_atual < 0 %}red{% endif %}">R$ {{ lucro_atual|format_brl }} / mês</div>
            <div class="explain-box">
                <b>Entenda a conta:</b> Com faturamento médio de <b>R$ {{ cliente.fat|format_brl }}</b> e margem de <b>{{ "%.1f"|format(margem_pct) }}%</b>, sobram <b>R$ {{ margem_atual_rs|format_brl }}</b> depois dos custos diretos. Pagando a despesa fixa de <b>R$ {{ cliente.fixo|format_brl }}</b>, o resultado mensal da empresa hoje é de <b>R$ {{ lucro_atual|format_brl }}</b>.
            </div>
        </div>
        
        <!-- 1. PONTO DE EQUILÍBRIO -->
        <div class="card alert-blue">
            <div class="card-label">1. Faturamento Mínimo para Empatar (Ponto de Equilíbrio)</div>
            <div class="value blue">R$ {{ ponto_equilibrio|format_brl }} / mês</div>
            <div class="explain-box">
                <b>Por que esse valor?</b> Para pagar os <b>R$ {{ cliente.fixo|format_brl }}</b> de despesa fixa com uma margem de <b>{{ "%.1f"|format(margem_pct) }}%</b> por venda, você precisa faturar pelo menos <b>R$ {{ ponto_equilibrio|format_brl }}</b> por mês{% if vendas_pe > 0 %} (cerca de <b>{{ vendas_pe }} vendas/mês</b>){% endif %}. Abaixo disso, a empresa tira dinheiro do caixa para pagar as contas.
                {% if receita_recorrente > 0 %}
                <br>🔄 <b>Ajuda dos Contratos/Retornos:</b> Sua receita recorrente de <b>R$ {{ receita_recorrente|format_brl }}/mês</b> deixa <b>R$ {{ margem_recorrente_rs|format_brl }}</b> de sobra garantida e paga sozinha <b>{{ "%.0f"|format(cobertura_fixo_rec_pct) }}%</b> das despesas fixas antes mesmo de você fechar uma venda nova.
                {% else %}
                <br>🛒 <b>Venda Mês a Mês (0% garantido):</b> Como o negócio começa todo mês com o caixa de pedidos zerado, 100% desse valor precisa ser conquistado nas vendas do mês.
                {% endif %}
            </div>
        </div>
        
        <!-- 2. CENÁRIO DE ESTRESSE (-30%) -->
        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div class="card-label">2. Teste de Crise (Se as Vendas Caírem 30%)</div>
            <div class="value {% if lucro < 0 %}red{% endif %}">
                Vendas: R$ {{ fat_estresse|format_brl }} &nbsp;|&nbsp; Resultado: R$ {{ lucro|format_brl }}
            </div>
            <div class="explain-box">
                <b>O que acontece na queda:</b> Se o faturamento cair 30%, ele vai de R$ {{ cliente.fat|format_brl }} para <b>R$ {{ fat_estresse|format_brl }}</b>. Com margem de {{ "%.1f"|format(margem_pct) }}%, sobram <b>R$ {{ margem_estresse_rs|format_brl }}</b>. Descontando os R$ {{ cliente.fixo|format_brl }} de despesa fixa, o caixa fecha o mês em <b>R$ {{ lucro|format_brl }}</b>.
            </div>
        </div>

        <!-- 3. PROJEÇÃO NA META -->
        <div class="card alert-blue">
            <div class="card-label">3. Plano para Bater Sua Meta (R$ {{ meta_fat|format_brl }}/mês)</div>
            <div class="value blue" style="font-size: 22px;">
                Crescimento de +{{ "%.1f"|format(crescimento_necessario) }}% &nbsp;|&nbsp; Sobra Líquida na Meta: <span style="{% if lucro_na_meta < 0 %}color: #c0392b;{% endif %}">R$ {{ lucro_na_meta|format_brl }}</span>
            </div>
            <div class="explain-box">
                <b>Resultado na Meta:</b> Faturando <b>R$ {{ meta_fat|format_brl }}</b> com margem de {{ "%.1f"|format(margem_pct) }}%, sobram <b>R$ {{ margem_meta_rs|format_brl }}</b>. Pagando a despesa fixa de R$ {{ cliente.fixo|format_brl }}, o lucro líquido mensal passa a ser <b>R$ {{ lucro_na_meta|format_brl }}</b>.
            </div>

            {% if meta_abaixo_pe %}
            <div class="alerta-meta-pe">
                ⚠️ <b>Atenção com a Sua Meta:</b> Mesmo batendo a meta de <b>R$ {{ meta_fat|format_brl }}</b>, a empresa ainda terá prejuízo de <b>R$ {{ lucro_na_meta|format_brl }}/mês</b>, porque a meta está <b>R$ {{ diferenca_meta_pe|format_brl }}</b> abaixo do faturamento mínimo para empatar (R$ {{ ponto_equilibrio|format_brl }}).
            </div>
            {% endif %}

            {% if cliente.ticket_medio > 0 %}
            <div class="engenharia-box">
                🎯 <strong>O Que Precisa Acontecer nas Vendas (Ticket Médio R$ {{ cliente.ticket_medio|format_brl }}):</strong><br>
                {% if receita_recorrente > 0 %}
                    • <b>Base já Garantida:</b> Você já começa o mês com <b>R$ {{ receita_recorrente|format_brl }}/mês</b> (<b>~{{ vendas_recorrentes_txt }} contratos/retornos</b> ativos).<br>
                    • <b>Vendas Novas Necessárias:</b> Para chegar em <b>R$ {{ meta_fat|format_brl }}</b> ({{ vendas_meta }} vendas no total), falta conquistar <b>R$ {{ receita_nova_necessaria|format_brl }}/mês</b> em novos clientes — ou seja, <b>+{{ novas_vendas }} vendas novas por mês</b>{% if vendas_30d_informada %} (nos últimos 30 dias você fechou <b>{{ vendas_30d }}</b>){% endif %}.
                {% else %}
                    {% if cliente.modelo != 'produtos' and vendas_30d_informada and vendas_30d == 0 %}
                        • <span style="color: #c0392b;"><b>Alerta de Vendas Paradas:</b></span> Você informou <b>0 vendas fechadas nos últimos 30 dias</b> (mesmo tendo uma média histórica de R$ {{ cliente.fat|format_brl }}, que daria {{ vendas_atuais_txt }} vendas/mês).<br>
                        • Para bater <b>R$ {{ meta_fat|format_brl }}</b>, você precisa fechar <b>{{ vendas_meta }} vendas por mês</b> retomando o ritmo do zero.
                    {% else %}
                        • <b>Meta em Quantidade:</b> Para faturar <b>R$ {{ meta_fat|format_brl }}</b>, a operação precisa realizar <b>{{ vendas_meta }} vendas por mês</b> (um aumento de <b>+{{ novas_vendas }} vendas/mês</b> sobre o ritmo atual de {{ vendas_atuais_txt }}/mês).
                    {% endif %}
                {% endif %}

                {% if cliente.modelo in ['b2b', 'campo'] %}
                    <br>• <b>Orçamentos e Reuniões ({{ dias_uteis }} dias úteis):</b> Para fechar <b>{{ vendas_alvo_funil }} contrato(s)</b> com taxa de fechamento de <b>{{ "%.0f"|format(taxa_conv_usada) }}%</b> ({{ origem_taxa }}), você precisa fazer <b>{{ oportunidades_mes }} reuniões ou orçamentos/mês</b> (<b>~{{ oportunidades_dia }} por dia</b>).
                    <br>• <b>Rotina Diária de Prospecção:</b> Para conseguir <b>{{ oportunidades_dia }} reunião(ões)/orçamento(s) por dia</b>, a equipe precisa fazer <b>{{ tentativas_dia_total }} ligações/abordagens ativas por dia</b> ({{ esforco_por_vendedor }}/dia por pessoa) $\rightarrow$ gerando <b>{{ conexoes_dia_min }} a {{ conexoes_dia_max }} conversas reais por dia</b> (20% a 30% atendem) $\rightarrow$ transformando parte delas em proposta.
                {% elif cliente.modelo == 'servicos' %}
                    <br>• <b>Avaliações e Orçamentos ({{ dias_uteis }} dias úteis):</b> Para fechar <b>{{ vendas_alvo_funil }} novos atendimentos/mês</b> com fechamento de <b>{{ "%.0f"|format(taxa_conv_usada) }}%</b> ({{ origem_taxa }}), você precisa gerar <b>{{ oportunidades_mes }} avaliações/orçamentos/mês</b> (<b>~{{ oportunidades_dia }} por dia</b>).
                    <br>• <b>3 Fontes Diárias de Pacientes/Clientes:</b>
                    <br>&nbsp;&nbsp;1. <b>Indicação Pós-Atendimento (Mini-NPS):</b> Ao finalizar cada consulta/serviço, pergunte se o cliente gostou e peça <b>5 indicações</b>. Com média de 1 a 2 nomes reais por cliente atendido, você gera <b>~{{ indicacoes_dia }} indicações quentes por dia</b> a custo zero;
                    <br>&nbsp;&nbsp;2. <b>Retorno da Base (WhatsApp):</b> Chame <b>~{{ recall_dia }} clientes antigos por dia</b> (atendidos há 3 ou 6 meses);
                    <br>&nbsp;&nbsp;3. <b>Novos Interessados (Instagram/Google):</b> Atenda <b>~{{ leads_receptivos_dia }} contatos novos por dia</b> para completar a meta diária.
                {% else %}
                    <br>• <b>Movimento Diário da Loja/WhatsApp ({{ dias_uteis }} dias úteis):</b> Para bater <b>{{ vendas_alvo_funil }} vendas no mês</b> (<b>~{{ vendas_dia_varejo }} vendas por dia</b>) com fechamento de <b>{{ "%.0f"|format(taxa_conv_usada) }}%</b> ({{ origem_taxa }}), a loja precisa atrair e atender <b>{{ oportunidades_mes }} clientes interessados/mês</b> — média de <b>{{ oportunidades_dia }} atendimentos qualificados por dia</b> (balcão + WhatsApp).
                {% endif %}

                {% if alerta_capacidade %}
                <div class="alerta-capacidade">
                    ⚠️ <b>Alerta de Capacidade da Equipe:</b> Esse volume exige <b>{{ esforco_por_vendedor }} contatos/dia por pessoa</b> (acima do limite saudável para 1 profissional). Avalie reforçar o time comercial ou usar anúncios/automação para trazer clientes prontos.
                </div>
                {% endif %}
            </div>
            {% endif %}
        </div>

        <!-- 4. FÔLEGO DO CAIXA -->
        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div class="card-label">4. Fôlego do Caixa (Quanto Tempo o Dinheiro Aguenta na Crise)</div>
            <div class="value {% if lucro < 0 %}red{% endif %}" style="font-size: 18px;">
                {% if lucro < 0 %}
                    🔴 ATENÇÃO: Seu caixa aguenta {{ "%.1f"|format(meses_runway) }} meses (~{{ dias_runway }} dias).
                {% else %}
                    🟢 SEGURO: Seu caixa aguenta a crise sem ficar no vermelho.
                {% endif %}
            </div>
            <div class="explain-box">
                {% if lucro < 0 %}
                    <b>Entenda o prazo:</b> Se as vendas caírem 30% e a empresa tiver prejuízo de <b>R$ {{ lucro_abs|format_brl }}/mês</b>, os <b>R$ {{ cliente.caixa|format_brl }}</b> que você tem guardados hoje acabam em <b>{{ "%.1f"|format(meses_runway) }} meses</b> (~{{ dias_runway }} dias).
                {% else %}
                    <b>Por que está seguro?</b> Mesmo com queda de 30% nas vendas, a empresa continua dando lucro de <b>R$ {{ lucro|format_brl }}/mês</b> sem precisar gastar os <b>R$ {{ cliente.caixa|format_brl }}</b> guardados no caixa.
                {% endif %}
            </div>
        </div>

        <div class="prescricao-card">
            <div class="prescricao-title">PLANO DE AÇÃO PRÁTICO (O QUE FAZER AGORA?)</div>
            <div class="lista-acoes">
                {% for item in acao %}
                    <p>{{ item|safe }}</p>
                {% endfor %}
            </div>
        </div>

        <div class="metricas-cegas-card {% if qtd_cegas == 0 %}all-ok{% endif %}">
            {% if qtd_cegas > 0 %}
                <span class="mc-badge">🚨 {{ qtd_cegas }} de 4 Números no Escuro</span>
                <h3 class="mc-title">RADAR DE CONTROLE: PONTOS CEGOS DA EMPRESA</h3>
                <p class="mc-intro">Veja quais indicadores você já controla e onde o dinheiro pode estar escapando sem você perceber:</p>
            {% else %}
                <span class="mc-badge ok">✅ Gestão 100% Monitorada</span>
                <h3 class="mc-title ok">RADAR DE CONTROLE: TODOS OS NÚMEROS NA MÃO</h3>
                <p class="mc-intro">Parabéns! Sua empresa acompanha os 4 indicadores essenciais de vendas e caixa:</p>
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
                <p class="mc-footer">Gerenciar a empresa sem esses {{ qtd_cegas }} número(s) faz você perder margem e vendas todos os dias no escuro.</p>
            {% endif %}
        </div>
        
        {% if lucro < 0 %}
        <div class="consequencia">
            <h4>⚠️ O QUE ACONTECE SE NADA FOR FEITO</h4>
            <p>Se essas ações não forem colocadas em prática agora, o dinheiro em caixa será consumido em <strong>{{ "%.1f"|format(meses_runway) }} meses (~{{ dias_runway }} dias)</strong>, obrigando a empresa a pegar empréstimos caros no banco ou travar a operação.</p>
        </div>
        {% endif %}

        <div class="botoes">
            <a href="https://wa.me/5581979091165?text=Olá,%20acabei%20de%20gerar%20meu%20laudo%20no%20Doutor%20Caixa%20({{ cliente.nome }})%20e%20quero%20ajuda%20para%20aplicar%20o%20plano." target="_blank" class="btn btn-wpp">💬 Falar com Especialista Agora</a>
            <a href="/baixar_pdf/{{ cnpj }}" class="btn">📄 Baixar Laudo em PDF</a>
            <a href="/" class="btn btn-outline">Nova Consulta</a>
        </div>

        <div class="dash-footer">
            Doutor Caixa é uma empresa da <strong>MaqTrak</strong> - Hub de Soluções em Inteligência de Mercado.
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_BLOQUEIO = r"""
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
    fator_margem = margem_pct / 100.0
    modelo = cliente.get('modelo', 'produtos')

    nomes_motor = {
        "b2b": "Consultoria / B2B & Contratos",
        "campo": "Manutenção & Serviços de Campo",
        "servicos": "Clínicas & Serviços por Agenda",
        "produtos": "Comércio / Varejo / Distribuição"
    }
    nome_motor_comercial = nomes_motor.get(modelo, modelo.upper())

    # 0. Cenário Atual
    margem_atual_rs = cliente['fat'] * fator_margem
    lucro_atual = margem_atual_rs - cliente['fixo']

    # 1. Ponto de Equilíbrio & Cobertura pela Recorrência
    ponto_equilibrio = cliente['fixo'] / fator_margem
    receita_recorrente = 0.0 if modelo == 'produtos' else float(cliente.get('receita_recorrente') or 0.0)
    margem_recorrente_rs = receita_recorrente * fator_margem
    cobertura_fixo_rec_pct = (margem_recorrente_rs / cliente['fixo'] * 100) if (receita_recorrente > 0 and cliente['fixo'] > 0) else 0.0

    # 2. Cenário de Estresse (-30%)
    fat_estresse = cliente['fat'] * 0.70
    margem_estresse_rs = fat_estresse * fator_margem
    lucro = margem_estresse_rs - cliente['fixo']
    lucro_abs = abs(lucro)
    meses_runway = cliente['caixa'] / lucro_abs if lucro < 0 else 0
    dias_runway = round(meses_runway * 30)

    # 3. Projeção na Meta
    meta_fat = cliente['meta_fat']
    crescimento_necessario = ((meta_fat - cliente['fat']) / cliente['fat']) * 100 if cliente['fat'] > 0 else 0
    margem_meta_rs = meta_fat * fator_margem
    lucro_na_meta = margem_meta_rs - cliente['fixo']
    meta_abaixo_pe = meta_fat < ponto_equilibrio
    diferenca_meta_pe = max(0.0, ponto_equilibrio - meta_fat)

    # 4. Engenharia Reversa Comercial Calibrada por Ramo
    tm = cliente.get('ticket_medio', 0.0)
    vendas_30d = int(cliente.get('vendas_30d', -1))
    vendas_30d_informada = (modelo != 'produtos') and (vendas_30d >= 0)
    qtd_vendedores = 1 if modelo == 'produtos' else max(1, int(cliente.get('qtd_vendedores') or 1))
    receita_nova_necessaria = max(0.0, meta_fat - receita_recorrente)

    dias_uteis = 25 if modelo == 'produtos' else 22

    if cliente.get('tem_conversao') and cliente.get('taxa_conversao', 0) > 0:
        taxa_conv_usada = float(cliente['taxa_conversao'])
        origem_taxa = "sua taxa real"
    else:
        if modelo in ('b2b', 'campo'):
            taxa_conv_usada = 15.0
            origem_taxa = "média de 15% do setor"
        elif modelo == 'servicos':
            taxa_conv_usada = 25.0
            origem_taxa = "média de 25% em clínicas"
        else:
            taxa_conv_usada = 30.0
            origem_taxa = "média de 30% no varejo"

    if tm > 0:
        vendas_atuais_dec = cliente['fat'] / tm
        vendas_atuais_txt = f"{vendas_atuais_dec:.1f}".replace(".", ",")
        vendas_recorrentes_dec = receita_recorrente / tm
        vendas_recorrentes_txt = f"{vendas_recorrentes_dec:.1f}".replace(".", ",")
        vendas_meta = math.ceil(meta_fat / tm)
        vendas_pe = math.ceil(ponto_equilibrio / tm)

        if receita_recorrente > 0:
            novas_vendas = max(0, math.ceil(receita_nova_necessaria / tm))
            vendas_alvo_funil = max(1, novas_vendas) if meta_fat > receita_recorrente else 0
        elif vendas_30d_informada:
            novas_vendas = max(0, vendas_meta - vendas_30d)
            vendas_alvo_funil = vendas_meta if vendas_30d == 0 else max(1, novas_vendas)
        else:
            novas_vendas = max(0, math.ceil((meta_fat - cliente['fat']) / tm))
            vendas_alvo_funil = vendas_meta
    else:
        vendas_atuais_dec = 0.0
        vendas_atuais_txt = "0"
        vendas_recorrentes_dec = 0.0
        vendas_recorrentes_txt = "0"
        vendas_meta = 0
        vendas_pe = 0
        novas_vendas = 0
        vendas_alvo_funil = 0

    oportunidades_mes = math.ceil(vendas_alvo_funil / (taxa_conv_usada / 100.0)) if vendas_alvo_funil > 0 else 0
    oportunidades_dia = math.ceil(oportunidades_mes / dias_uteis) if oportunidades_mes > 0 else 0
    vendas_dia_varejo = math.ceil(vendas_alvo_funil / dias_uteis) if vendas_alvo_funil > 0 else 0

    # Esforço diário realista por modelo comercial
    if modelo in ('b2b', 'campo'):
        tentativas_dia_total = max(40, oportunidades_dia * 17) if oportunidades_dia > 0 else 40
        conexoes_dia_min = max(1, round(tentativas_dia_total * 0.20))
        conexoes_dia_max = max(2, round(tentativas_dia_total * 0.30))
        indicacoes_dia = 0
        leads_receptivos_dia = 0
        recall_dia = 0
        esforco_por_vendedor = math.ceil(tentativas_dia_total / qtd_vendedores)
        alerta_capacidade = esforco_por_vendedor > 60
    elif modelo == 'servicos':
        tentativas_dia_total = 0
        conexoes_dia_min = 0
        conexoes_dia_max = 0
        atendimentos_base_dia = max(2, math.ceil(max(vendas_atuais_dec, 1) / dias_uteis))
        indicacoes_dia = max(3, math.ceil(atendimentos_base_dia * 1.5))
        contatos_totais_clinica_dia = max(5, oportunidades_dia * 3) if oportunidades_dia > 0 else 5
        leads_receptivos_dia = max(2, contatos_totais_clinica_dia - indicacoes_dia)
        recall_dia = max(12, math.ceil((vendas_recorrentes_dec * 1.5) / dias_uteis))
        esforco_por_vendedor = math.ceil((leads_receptivos_dia + recall_dia) / qtd_vendedores)
        alerta_capacidade = esforco_por_vendedor > 70
    else:
        tentativas_dia_total = 0
        conexoes_dia_min = 0
        conexoes_dia_max = 0
        indicacoes_dia = 0
        leads_receptivos_dia = 0
        recall_dia = 0
        esforco_por_vendedor = 0
        alerta_capacidade = False

    # Cálculos explícitos de corte de despesa fixa (15%) e impacto no Ponto de Equilíbrio
    corte_15_rs = cliente['fixo'] * 0.15
    fixo_pos_corte = cliente['fixo'] - corte_15_rs
    pe_pos_corte = fixo_pos_corte / fator_margem
    vendas_pe_pos_corte = math.ceil(pe_pos_corte / tm) if tm > 0 else 0
    pct_deficit_fixo = (abs(lucro_atual) / cliente['fixo'] * 100) if (lucro_atual < 0 and cliente['fixo'] > 0) else 0.0

    # Radar de Pontos Cegos vs Controlados
    radar = []
    qtd_cegas = 0

    if cliente.get('tem_cac'):
        radar.append({
            "controlada": True,
            "titulo": f"1. Custo por Cliente Controlado: R$ {format_brl(cliente['cac'])}",
            "descricao": "Você já sabe quanto investe para trazer 1 cliente novo. Agora foque nos canais que trazem clientes mais baratos."
        })
    else:
        qtd_cegas += 1
        radar.append({
            "controlada": False,
            "titulo": "1. Custo para Trazer 1 Cliente (No Escuro)",
            "descricao": "Você não sabe quanto gasta em divulgação e vendas para conquistar cada cliente novo."
        })

    if cliente.get('tem_ltv'):
        rel_ltv_cac = ""
        if cliente.get('tem_cac') and cliente.get('cac', 0) > 0:
            ratio = cliente['ltv'] / cliente['cac']
            rel_ltv_cac = f" (Retorno de {ratio:.1f}x sobre o custo de aquisição - {'Saudável' if ratio >= 3 else 'Atenção: ideal acima de 3x'})."
        radar.append({
            "controlada": True,
            "titulo": f"2. Gasto Total por Cliente Controlado: R$ {format_brl(cliente['ltv'])}",
            "descricao": f"Você acompanha quanto cada cliente deixa na empresa.{rel_ltv_cac}"
        })
    else:
        qtd_cegas += 1
        radar.append({
            "controlada": False,
            "titulo": "2. Quanto Cada Cliente Gasta no Tempo (No Escuro)",
            "descricao": "Você não mede quanto dinheiro cada cliente deixa na empresa ao voltar para comprar de novo."
        })

    if cliente.get('tem_conversao'):
        radar.append({
            "controlada": True,
            "titulo": f"3. Taxa de Fechamento Controlada: {cliente['taxa_conversao']}%",
            "descricao": f"Funil medido: precisa de ~{oportunidades_mes} orçamentos/atendimentos no mês ({oportunidades_dia}/dia)." if oportunidades_mes > 0 else "Você já acompanha quantos orçamentos viram venda."
        })
    else:
        qtd_cegas += 1
        radar.append({
            "controlada": False,
            "titulo": "3. Taxa de Fechamento de Vendas (No Escuro)",
            "descricao": f"Usamos a {origem_taxa} no cálculo. Anote quantos atendimentos viram venda para ter controle real."
        })

    if cliente.get('tem_ciclo'):
        dias = cliente['ciclo_financeiro']
        aviso_ciclo = "Atenção: prazo longo exige mais dinheiro parado no caixa." if dias > 30 else "Prazos de recebimento e pagamento bem equilibrados."
        radar.append({
            "controlada": True,
            "titulo": f"4. Prazo do Dinheiro Controlado: {dias} dias",
            "descricao": f"Diferença de prazos mapeada. {aviso_ciclo}"
        })
    else:
        qtd_cegas += 1
        radar.append({
            "controlada": False,
            "titulo": "4. Prazo Entre Pagar e Receber (No Escuro)",
            "descricao": "Risco de vender bem, mas ficar sem dinheiro no caixa por dar prazo longo ao cliente e pagar fornecedor à vista."
        })

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
        "nome_motor_comercial": nome_motor_comercial,
        "dias_uteis": dias_uteis,
        "taxa_conv_usada": taxa_conv_usada,
        "origem_taxa": origem_taxa,
        "margem_pct": margem_pct,
        "margem_atual_rs": margem_atual_rs,
        "lucro_atual": lucro_atual,
        "fat_estresse": fat_estresse,
        "margem_estresse_rs": margem_estresse_rs,
        "lucro": lucro,
        "lucro_abs": lucro_abs,
        "meses_runway": meses_runway,
        "dias_runway": dias_runway,
        "ponto_equilibrio": ponto_equilibrio,
        "pe_pos_corte": pe_pos_corte,
        "vendas_pe_pos_corte": vendas_pe_pos_corte,
        "receita_recorrente": receita_recorrente,
        "margem_recorrente_rs": margem_recorrente_rs,
        "cobertura_fixo_rec_pct": cobertura_fixo_rec_pct,
        "receita_nova_necessaria": receita_nova_necessaria,
        "meta_fat": meta_fat,
        "crescimento_necessario": crescimento_necessario,
        "margem_meta_rs": margem_meta_rs,
        "lucro_na_meta": lucro_na_meta,
        "meta_abaixo_pe": meta_abaixo_pe,
        "diferenca_meta_pe": diferenca_meta_pe,
        "vendas_30d": vendas_30d,
        "vendas_30d_informada": vendas_30d_informada,
        "vendas_atuais_txt": vendas_atuais_txt,
        "vendas_recorrentes_txt": vendas_recorrentes_txt,
        "vendas_meta": vendas_meta,
        "vendas_pe": vendas_pe,
        "novas_vendas": novas_vendas,
        "vendas_alvo_funil": vendas_alvo_funil,
        "oportunidades_mes": oportunidades_mes,
        "oportunidades_dia": oportunidades_dia,
        "vendas_dia_varejo": vendas_dia_varejo,
        "tentativas_dia_total": tentativas_dia_total,
        "conexoes_dia_min": conexoes_dia_min,
        "conexoes_dia_max": conexoes_dia_max,
        "indicacoes_dia": indicacoes_dia,
        "leads_receptivos_dia": leads_receptivos_dia,
        "recall_dia": recall_dia,
        "qtd_vendedores": qtd_vendedores,
        "esforco_por_vendedor": esforco_por_vendedor,
        "alerta_capacidade": alerta_capacidade,
        "corte_15_rs": corte_15_rs,
        "fixo_pos_corte": fixo_pos_corte,
        "pct_deficit_fixo": pct_deficit_fixo,
        "radar_metricas": radar,
        "qtd_cegas": qtd_cegas,
        "comparativo": comparativo
    }


def gerar_textos_prescricao(cliente, m):
    modelo = cliente.get('modelo', 'produtos')

    # Item 1: Corte de Despesa Fixa em linguagem direta
    if m['lucro_atual'] < 0:
        item1_tit = "1. CORTE URGENTE DE DESPESAS FIXAS: "
        item1_desc = (
            f"Hoje a empresa fecha o mês no vermelho em R$ {format_brl(abs(m['lucro_atual']))} ({m['pct_deficit_fixo']:.0f}% da despesa fixa). "
            f"Corte imediatamente 15% dos gastos fixos não essenciais (economia de R$ {format_brl(m['corte_15_rs'])}/mês, "
            f"baixando as despesas fixas de R$ {format_brl(cliente['fixo'])} para R$ {format_brl(m['fixo_pos_corte'])}/mês) para aliviar o caixa enquanto aumenta as vendas."
        )
    elif m['lucro'] < 0:
        item1_tit = "1. PROTEÇÃO DO CAIXA CONTRA QUEDA DE VENDAS: "
        item1_desc = (
            f"Hoje a empresa dá lucro, mas se as vendas caírem 30% você terá prejuízo de R$ {format_brl(m['lucro_abs'])}/mês. "
            f"Deixe mapeado um corte rápido de 15% nas despesas fixas (R$ {format_brl(m['corte_15_rs'])}/mês) para não queimar sua reserva."
        )
    else:
        item1_tit = "1. CRESCIMENTO COM CAIXA SEGURO: "
        item1_desc = "Use a folga de lucro atual para investir apenas nos canais de divulgação que já trazem clientes pagantes, sem mexer na reserva de caixa."

    # Item 2: Rotina Comercial 100% Adaptada ao Ramo
    if modelo == 'b2b':
        item2_tit = "2. ROTINA DIÁRIA DE PROSPECÇÃO E CONTRATOS: "
        item2_desc = (
            f"Para gerar {m['oportunidades_mes']} propostas/mês (~{m['oportunidades_dia']}/dia em 22 dias úteis) e fechar {m['vendas_alvo_funil']} contrato(s) "
            f"(taxa de {m['taxa_conv_usada']:.0f}%), faça {m['tentativas_dia_total']} ligações/abordagens ativas por dia "
            f"({m['esforco_por_vendedor']}/dia por pessoa) para conseguir {m['conexoes_dia_min']} a {m['conexoes_dia_max']} conversas reais/dia. "
            f"Cobre todos os orçamentos parados diariamente e ofereça pacotes mensais de 6 a 12 meses para garantir receita fixa."
        )
    elif modelo == 'campo':
        item2_tit = "2. VISITAS TÉCNICAS E CONTRATOS DE MANUTENÇÃO: "
        item2_desc = (
            f"Faça {m['tentativas_dia_total']} abordagens ativas/dia ({m['esforco_por_vendedor']}/dia por pessoa) para conseguir "
            f"{m['conexoes_dia_min']} a {m['conexoes_dia_max']} conversas reais e agendar ~{m['oportunidades_dia']} visita(s) técnica(s)/orçamento(s)/dia "
            f"({m['oportunidades_mes']}/mês). Transforme atendimentos avulsos em contratos mensais de manutenção preventiva."
        )
    elif modelo == 'servicos':
        item2_tit = "2. PESQUISA RÁPIDA COM PEDIDO DE 5 INDICAÇÕES + RETORNO DE BASE: "
        item2_desc = (
            f"Execute 3 ações todos os dias (22 dias úteis) para gerar {m['oportunidades_dia']} avaliações/orçamentos/dia: "
            f"(a) logo após cada atendimento, pergunte se o cliente gostou (Mini-NPS) e peça 5 indicações de amigos/familiares "
            f"(gerando ~{m['indicacoes_dia']} indicações quentes/dia a custo zero); "
            f"(b) chame {m['recall_dia']} clientes antigos/dia no WhatsApp para retorno (3 e 6 meses); "
            f"(c) responda em até 5 minutos os ~{m['leads_receptivos_dia']} novos interessados/dia do Instagram/Google e confirme a agenda 24h antes."
        )
    else:
        item2_tit = "2. ATRAÇÃO DE CLIENTES, BALCÃO E COMPRA MELHOR (VAREJO): "
        item2_desc = (
            f"Para bater ~{m['vendas_dia_varejo']} vendas/dia (25 dias úteis) e atender {m['oportunidades_dia']} clientes interessados/dia na loja e no WhatsApp: "
            f"(a) crie ofertas chamativas em produtos-isca para atrair fluxo sem derrubar sua margem geral; "
            f"(b) ofereça sempre um item complementar no balcão/WhatsApp para aumentar o valor de cada venda e dispare novidades para clientes antigos; "
            f"(c) negocie prazos maiores e descontos à vista com fornecedores para sobrar mais dinheiro em cada produto vendido."
        )

    # Item 3: Alvo Prioritário
    if m['lucro'] < 0:
        item3_tit = "3. META NÚMERO 1 (SAIR DO VERMELHO): "
        pe_v = f" ({m['vendas_pe']} vendas/mês)" if m['vendas_pe'] > 0 else ""
        pe_corte_v = f" ({m['vendas_pe_pos_corte']} vendas/mês)" if m['vendas_pe_pos_corte'] > 0 else ""
        item3_desc = (
            f"Concentre toda a equipe para atingir o faturamento mínimo de R$ {format_brl(m['ponto_equilibrio'])}/mês{pe_v}. "
            f"Com o corte de 15% nas despesas fixas (Item 1), esse mínimo cai para R$ {format_brl(m['pe_pos_corte'])}/mês{pe_corte_v}, "
            f"fazendo a empresa empatar as contas muito mais rápido."
        )
    else:
        item3_tit = "3. CAMINHO PARA BATER SUA META DE FATURAMENTO: "
        txt_v = f" (+{m['novas_vendas']} vendas novas/mês)" if m['novas_vendas'] > 0 else ""
        item3_desc = (
            f"Mantenha a rotina diária de vendas acima para chegar em R$ {format_brl(m['meta_fat'])}/mês{txt_v} "
            f"e aumentar o lucro líquido para R$ {format_brl(m['lucro_na_meta'])}/mês."
        )

    return [
        (item1_tit, item1_desc),
        (item2_tit, item2_desc),
        (item3_tit, item3_desc)
    ]


def renderizar_laudo(cnpj_limpo):
    cliente = buscar_cliente_db(cnpj_limpo)
    if not cliente:
        return render_template_string(TEMPLATE_HOME, erro="CNPJ não encontrado. Por favor, gere um novo diagnóstico.")

    if not cliente['ativo']:
        return render_template_string(TEMPLATE_BLOQUEIO)

    m = calcular_metricas_laudo(cliente)
    itens = gerar_textos_prescricao(cliente, m)
    acao_html = [f"<strong>{tit}</strong>{desc}" for tit, desc in itens]

    return render_template_string(
        TEMPLATE_DASHBOARD,
        cliente=cliente,
        cnpj=cnpj_limpo,
        acao=acao_html,
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

        modelo = request.form.get('modelo', 'produtos')
        if modelo == 'produtos':
            receita_recorrente = 0.0
            vendas_30d = -1
            qtd_vendedores = 1
        elif modelo == 'servicos':
            pct_rec = float(str(request.form.get('pct_recorrencia', '0') or 0).replace(',', '.'))
            pct_rec = max(0.0, min(100.0, pct_rec))
            receita_recorrente = fat * (pct_rec / 100.0)
            vendas_30d_raw = request.form.get('vendas_30d', '').strip()
            vendas_30d = int(float(vendas_30d_raw)) if vendas_30d_raw != '' else -1
            qtd_vendedores_raw = request.form.get('qtd_vendedores', '1').strip()
            qtd_vendedores = max(1, int(float(qtd_vendedores_raw))) if qtd_vendedores_raw != '' else 1
        else:
            receita_recorrente = parse_brl(request.form.get('receita_recorrente_rs', '0'))
            vendas_30d_raw = request.form.get('vendas_30d', '').strip()
            vendas_30d = int(float(vendas_30d_raw)) if vendas_30d_raw != '' else -1
            qtd_vendedores_raw = request.form.get('qtd_vendedores', '1').strip()
            qtd_vendedores = max(1, int(float(qtd_vendedores_raw))) if qtd_vendedores_raw != '' else 1

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
            "modelo": modelo,
            "caixa": parse_brl(request.form.get('caixa', '0')),
            "fat": fat,
            "fixo": parse_brl(request.form.get('fixo', '0')),
            "margem": margem,
            "ticket_medio": parse_brl(request.form.get('ticket_medio', '0')),
            "meta_fat": parse_brl(request.form.get('meta_fat', str(fat * 1.3))),
            "vendas_30d": vendas_30d,
            "qtd_vendedores": qtd_vendedores,
            "receita_recorrente": receita_recorrente,
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
            self.cell(148, 8, 'LAUDO FINANCEIRO E COMERCIAL', border=0, align='R')
            self.set_font('helvetica', '', 8.5)
            self.set_text_color(107, 122, 112)
            self.set_xy(50, 24)
            self.cell(148, 6, 'DIAGNÓSTICO DE CAIXA, MARGEM E RITMO DE VENDAS', border=0, align='R')
            self.set_draw_color(213, 232, 220)
            self.set_line_width(0.4)
            self.line(12, 43, 198, 43)
            self.set_y(49)

        def footer(self):
            self.set_y(-16)
            self.set_font('helvetica', '', 7.8)
            self.set_text_color(120, 130, 124)
            self.cell(0, 4.5, pdf_safe(f'Doutor Caixa | Inteligência Financeira & Comercial  -  Página {self.page_no()}'), ln=1, align='C')
            self.set_font('helvetica', '', 7.2)
            self.set_text_color(140, 150, 144)
            self.cell(0, 4.2, pdf_safe('Doutor Caixa é uma empresa da MaqTrak - Hub de Soluções em Inteligência de Mercado.'), align='C')

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=19)
    pdf.add_page()

    def desenhar_card(y_topo, altura, cor_fundo, cor_barra):
        pdf.set_fill_color(*cor_fundo)
        pdf.rect(12, y_topo, 186, altura, 'F')
        pdf.set_fill_color(*cor_barra)
        pdf.rect(12, y_topo, 2.5, altura, 'F')

    # 1. Identificação e Premissas
    y = pdf.get_y()
    desenhar_card(y, 22, (247, 250, 248), (15, 46, 28))
    pdf.set_xy(19, y + 3)
    pdf.set_font('helvetica', 'B', 10)
    pdf.set_text_color(15, 46, 28)
    pdf.cell(175, 5.2, pdf_safe(f"EMPRESA: {cliente['nome']}  |  CNPJ: {format_cnpj(cnpj)}  |  {m['nome_motor_comercial']}"), ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 8.4)
    pdf.set_text_color(80, 95, 86)
    rec_txt = f" | Garantido: R$ {format_brl(m['receita_recorrente'])}" if m['receita_recorrente'] > 0 else " | Venda mês a mês (0% fixo)"
    pdf.cell(175, 4.8, pdf_safe(f"Fat. Médio: R$ {format_brl(cliente['fat'])} | Desp. Fixa: R$ {format_brl(cliente['fixo'])} | Sobra: {m['margem_pct']:.1f}% | Caixa: R$ {format_brl(cliente['caixa'])}{rec_txt}"), ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 8.4)
    pdf.set_text_color(192, 57, 43) if m['lucro_atual'] < 0 else pdf.set_text_color(15, 46, 28)
    pdf.cell(175, 4.8, pdf_safe(f"Resultado Atual: R$ {format_brl(m['lucro_atual'])}/mês (Sobra das vendas: R$ {format_brl(m['margem_atual_rs'])} - Despesa Fixa: R$ {format_brl(cliente['fixo'])})"), ln=1)
    pdf.set_y(y + 22 + 4.0)

    # 2. Ponto de Equilíbrio
    y = pdf.get_y()
    alt_pe = 26.5 if m['receita_recorrente'] > 0 else 22.5
    desenhar_card(y, alt_pe, (235, 245, 251), (41, 128, 185))
    pdf.set_xy(19, y + 2.6)
    pdf.set_font('helvetica', 'B', 8.4)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 4.4, "1. FATURAMENTO MÍNIMO PARA EMPATAR (PONTO DE EQUILÍBRIO)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 13.5)
    pdf.set_text_color(41, 128, 185)
    pdf.cell(175, 6.2, f"R$ {format_brl(m['ponto_equilibrio'])} / mês", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 7.9)
    pdf.set_text_color(60, 70, 75)
    pe_vendas = f" = {m['vendas_pe']} vendas/mês" if m['vendas_pe'] > 0 else ""
    pdf.cell(175, 4.3, pdf_safe(f"Conta: Despesa Fixa (R$ {format_brl(cliente['fixo'])}) / Margem ({m['margem_pct']:.1f}%) = R$ {format_brl(m['ponto_equilibrio'])}{pe_vendas} para empatar."), ln=1)
    if m['receita_recorrente'] > 0:
        pdf.set_x(19)
        pdf.set_font('helvetica', 'B', 7.9)
        pdf.set_text_color(15, 46, 28)
        pdf.cell(175, 4.3, pdf_safe(f"Ajuda Recorrente: Sua base garantida de R$ {format_brl(m['receita_recorrente'])} já paga {m['cobertura_fixo_rec_pct']:.0f}% da despesa fixa."), ln=1)
    pdf.set_y(y + alt_pe + 4.0)

    # 3. Cenário de Estresse
    y = pdf.get_y()
    bg_color = (253, 237, 236) if is_critical else (232, 247, 238)
    bar_color = (192, 57, 43) if is_critical else (0, 200, 83)
    val_color = (192, 57, 43) if is_critical else (15, 46, 28)
    desenhar_card(y, 23.5, bg_color, bar_color)
    pdf.set_xy(19, y + 2.6)
    pdf.set_font('helvetica', 'B', 8.4)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 4.4, "2. TESTE DE CRISE (SE AS VENDAS CAÍREM 30%)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(*val_color)
    pdf.cell(175, 6.4, f"Vendas na Crise: R$ {format_brl(m['fat_estresse'])}   |   Resultado: R$ {format_brl(m['lucro'])}/mês", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 7.9)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(175, 4.3, pdf_safe(f"Conta: Vendas (-30%) deixam R$ {format_brl(m['margem_estresse_rs'])} ({m['margem_pct']:.1f}%) - Desp. Fixa (R$ {format_brl(cliente['fixo'])}) = R$ {format_brl(m['lucro'])}."), ln=1)
    pdf.set_y(y + 23.5 + 4.0)

    # 4. Projeção na Meta + Engenharia Reversa por Ramo
    y = pdf.get_y()
    alt_meta = 38.5 if (cliente['ticket_medio'] > 0 and cliente['modelo'] == 'servicos') else (34.5 if cliente['ticket_medio'] > 0 else 23.5)
    desenhar_card(y, alt_meta, (235, 245, 251), (41, 128, 185))
    pdf.set_xy(19, y + 2.6)
    pdf.set_font('helvetica', 'B', 8.4)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 4.3, f"3. PLANO PARA BATER SUA META (R$ {format_brl(m['meta_fat'])}/MÊS)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 10.5)
    pdf.set_text_color(41, 128, 185)
    pdf.cell(175, 5.8, f"Crescimento: +{m['crescimento_necessario']:.1f}%  |  Sobra Líquida na Meta: R$ {format_brl(m['lucro_na_meta'])}/mês", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 7.8)
    pdf.set_text_color(60, 70, 75)
    aviso_pe_pdf = " [ATENÇÃO: Meta abaixo do mínimo para empatar!]" if m['meta_abaixo_pe'] else ""
    pdf.cell(175, 4.3, pdf_safe(f"Conta: Sobra na meta (R$ {format_brl(m['margem_meta_rs'])}) - Desp. Fixa (R$ {format_brl(cliente['fixo'])}) = R$ {format_brl(m['lucro_na_meta'])}.{aviso_pe_pdf}"), ln=1)
    if cliente['ticket_medio'] > 0:
        pdf.set_x(19)
        pdf.set_font('helvetica', 'B', 7.9)
        pdf.set_text_color(27, 79, 114)
        if m['receita_recorrente'] > 0:
            origem_v = f"Base garantida: R$ {format_brl(m['receita_recorrente'])} (~{m['vendas_recorrentes_txt']} un.) + {m['novas_vendas']} vendas novas/mês"
        else:
            origem_v = f"Meta total: {m['vendas_meta']} vendas/mês (+{m['novas_vendas']} vendas sobre o ritmo atual)"
        pdf.cell(175, 4.3, pdf_safe(f"Vendas: {origem_v}."), ln=1)
        pdf.set_x(19)
        if cliente['modelo'] in ('b2b', 'campo'):
            linha_funil = f"Prospecção (22d): {m['oportunidades_mes']} propostas/mês (~{m['oportunidades_dia']}/dia) -> {m['tentativas_dia_total']} abordagens/dia ({m['conexoes_dia_min']}-{m['conexoes_dia_max']} conversas)."
            pdf.cell(175, 4.3, pdf_safe(linha_funil), ln=1)
        elif cliente['modelo'] == 'servicos':
            linha_funil1 = f"Agenda (22d): {m['oportunidades_mes']} avaliações/mês (~{m['oportunidades_dia']}/dia)."
            linha_funil2 = f"Fontes diárias: ~{m['indicacoes_dia']} indicações (Mini-NPS 5 nomes) + {m['recall_dia']} retornos WhatsApp + {m['leads_receptivos_dia']} novos."
            pdf.cell(175, 4.1, pdf_safe(linha_funil1), ln=1)
            pdf.set_x(19)
            pdf.cell(175, 4.1, pdf_safe(linha_funil2), ln=1)
        else:
            linha_funil = f"Varejo (25d): ~{m['vendas_dia_varejo']} vendas/dia -> {m['oportunidades_dia']} atendimentos interessados/dia na loja e WhatsApp."
            pdf.cell(175, 4.3, pdf_safe(linha_funil), ln=1)
    pdf.set_y(y + alt_meta + 4.0)

    # 5. Fôlego do Caixa
    y = pdf.get_y()
    desenhar_card(y, 19, bg_color, bar_color)
    pdf.set_xy(19, y + 2.5)
    pdf.set_font('helvetica', 'B', 8.4)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 4.3, "4. FÔLEGO DO CAIXA (QUANTO TEMPO O DINHEIRO AGUENTA NA CRISE)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 8.2)
    pdf.set_text_color(40, 40, 40)
    if is_critical:
        texto_runway = f"ATENÇÃO: Caixa atual (R$ {format_brl(cliente['caixa'])}) / Prejuízo na crise (R$ {format_brl(m['lucro_abs'])}/mês) = {m['meses_runway']:.1f} meses (~{m['dias_runway']} dias) de fôlego."
    else:
        texto_runway = f"SEGURO: Mesmo com queda de 30%, a empresa continua dando lucro e preserva os R$ {format_brl(cliente['caixa'])} em caixa."
    pdf.multi_cell(175, 4.3, pdf_safe(texto_runway))
    pdf.set_y(y + 19 + 4.0)

    # 6. Plano de Ação Prático Calibrado por Ramo
    itens_prescricao = gerar_textos_prescricao(cliente, m)

    pdf.set_font('helvetica', '', 8.2)
    altura_texto_presc = 0
    for tit, desc in itens_prescricao:
        linhas = max(1, math.ceil(pdf.get_string_width(tit + desc) / 166))
        altura_texto_presc += (linhas * 4.3) + 1.6
    altura_card_presc = 12 + altura_texto_presc

    y = pdf.get_y()
    desenhar_card(y, altura_card_presc, (15, 46, 28), (0, 200, 83))
    pdf.set_xy(19, y + 2.8)
    pdf.set_font('helvetica', 'B', 9.5)
    pdf.set_text_color(0, 200, 83)
    pdf.cell(175, 4.5, "PLANO DE AÇÃO PRÁTICO (O QUE FAZER AGORA?)", ln=1)

    pdf.set_left_margin(19)
    pdf.set_right_margin(16)
    pdf.set_y(y + 9.0)
    pdf.set_text_color(245, 248, 246)
    for tit, desc in itens_prescricao:
        pdf.set_x(19)
        pdf.set_font('helvetica', 'B', 8.2)
        pdf.write(4.3, pdf_safe(tit))
        pdf.set_font('helvetica', '', 8.2)
        pdf.write(4.3, pdf_safe(desc + "\n"))
        pdf.ln(1.4)

    pdf.set_left_margin(12)
    pdf.set_right_margin(12)

    # PÁGINA 2: RADAR DE CONTROLE PERSONALIZADO + URGÊNCIA & QR CODE WHATSAPP
    pdf.add_page()
    y = pdf.get_y()
    altura_card_cegas = 96
    is_all_ok = m['qtd_cegas'] == 0

    pdf.set_fill_color(*((240, 253, 244) if is_all_ok else (255, 245, 245)))
    pdf.set_draw_color(*((0, 200, 83) if is_all_ok else (220, 76, 62)))
    pdf.set_line_width(0.5)
    pdf.rect(12, y, 186, altura_card_cegas, 'DF')
    pdf.set_fill_color(*((0, 200, 83) if is_all_ok else (192, 57, 43)))
    pdf.rect(12, y, 3.5, altura_card_cegas, 'F')

    pdf.set_xy(20, y + 4.5)
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(*((15, 46, 28) if is_all_ok else (192, 57, 43)))
    titulo_radar = "RADAR DE CONTROLE: TODOS OS NÚMEROS NA MÃO" if is_all_ok else f"ALERTA: {m['qtd_cegas']} DE 4 NÚMEROS IMPORTANTES ESTÃO NO ESCURO"
    pdf.cell(172, 6.2, titulo_radar, ln=1)

    pdf.set_x(20)
    pdf.set_font('helvetica', '', 9.3)
    pdf.set_text_color(50, 50, 50)
    pdf.multi_cell(172, 4.8, "Veja quais indicadores você já acompanha e onde o dinheiro pode estar escapando:")
    pdf.ln(2.5)

    for item in m['radar_metricas']:
        y_item = pdf.get_y()
        ok_m = item['controlada']
        pdf.set_fill_color(255, 255, 255)
        pdf.set_draw_color(*((183, 228, 199) if ok_m else (245, 183, 177)))
        pdf.set_line_width(0.3)
        pdf.rect(20, y_item, 172, 13.5, 'DF')
        pdf.set_fill_color(*((0, 200, 83) if ok_m else (192, 57, 43)))
        pdf.rect(20, y_item, 2, 13.5, 'F')
        pdf.set_xy(24, y_item + 2)
        pdf.set_font('helvetica', 'B', 9.2)
        pdf.set_text_color(*((15, 46, 28) if ok_m else (192, 57, 43)))
        status_tag = "[CONTROLADO] " if ok_m else "[NO ESCURO] "
        pdf.cell(165, 4.5, pdf_safe(status_tag + item['titulo']), ln=1)
        pdf.set_x(24)
        pdf.set_font('helvetica', '', 8.4)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(165, 4.5, pdf_safe(item['descricao']), ln=1)
        pdf.set_y(y_item + 15.2)

    pdf.set_x(20)
    pdf.set_font('helvetica', 'B', 9.2)
    pdf.set_text_color(*((15, 46, 28) if is_all_ok else (146, 43, 33)))
    rodape_radar = "Excelente controle dos números. Agora o foco é aumentar vendas e margem." if is_all_ok else "Gerenciar sem esses números faz você perder margem e vendas todos os dias sem notar."
    pdf.cell(172, 5.5, rodape_radar, ln=1)
    pdf.set_y(y + altura_card_cegas + 7)

    if is_critical:
        y_cons = pdf.get_y()
        desenhar_card(y_cons, 23, (253, 238, 217), (211, 84, 0))
        pdf.set_xy(19, y_cons + 3.2)
        pdf.set_font('helvetica', 'B', 9.8)
        pdf.set_text_color(160, 64, 0)
        pdf.cell(175, 5.2, "O QUE ACONTECE SE NADA FOR FEITO", ln=1)
        pdf.set_x(19)
        pdf.set_font('helvetica', '', 8.9)
        pdf.set_text_color(50, 50, 50)
        pdf.multi_cell(175, 4.5, f"Se essas ações não forem aplicadas agora, o dinheiro em caixa acabará em {m['meses_runway']:.1f} meses (~{m['dias_runway']} dias), obrigando a empresa a buscar empréstimos caros.")
        pdf.set_y(y_cons + 23 + 7)

    # BLOCO DE URGÊNCIA + QR CODE WHATSAPP + TELEFONE DIRETO
    y_cta = pdf.get_y()
    altura_cta = 46
    desenhar_card(y_cta, altura_cta, (15, 46, 28), (0, 200, 83))

    link_wpp = "https://wa.me/5581979091165?text=Olá,%20acabei%20de%20gerar%20meu%20laudo%20no%20Doutor%20Caixa%20e%20quero%20ajuda%20para%20aplicar%20o%20plano."

    pdf.set_xy(19, y_cta + 4.0)
    pdf.set_font('helvetica', 'B', 8.5)
    pdf.set_text_color(243, 156, 18)
    pdf.cell(128, 4.5, pdf_safe("CADA DIA SEM AÇÃO CUSTA MARGEM E DINHEIRO NO CAIXA."), ln=1)

    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(0, 200, 83)
    pdf.cell(128, 6.2, pdf_safe("FALE AGORA COM O DOUTOR CAIXA"), ln=1, link=link_wpp)

    pdf.set_x(19)
    pdf.set_font('helvetica', '', 8.4)
    pdf.set_text_color(235, 242, 238)
    pdf.multi_cell(128, 4.3, pdf_safe("Aponte a câmera do seu celular para o QR Code ao lado e fale agora com nossa equipe para destravar seu plano de ação:"))

    # Número do WhatsApp destacado em outro ponto do bloco
    y_num = y_cta + 31.5
    pdf.set_fill_color(24, 68, 42)
    pdf.rect(19, y_num, 88, 9.5, 'F')
    pdf.set_xy(22, y_num + 2.2)
    pdf.set_font('helvetica', 'B', 9.5)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(82, 5, pdf_safe("WhatsApp: (81) 9.7909.1165"), link=link_wpp)

    # QR Code à direita
    pdf.set_fill_color(255, 255, 255)
    pdf.rect(154, y_cta + 3.5, 36, 36, 'F')
    try:
        pdf.image('static/qrcode_whatsapp.png', x=155, y=y_cta + 4.5, w=34, h=34, link=link_wpp)
    except Exception:
        pdf.set_xy(154, y_cta + 18)
        pdf.set_font('helvetica', 'B', 7)
        pdf.set_text_color(15, 46, 28)
        pdf.cell(36, 4, "QR Code WhatsApp", align='C')

    pdf.set_xy(152, y_cta + 40.2)
    pdf.set_font('helvetica', 'B', 6.8)
    pdf.set_text_color(200, 220, 208)
    pdf.cell(40, 3.8, pdf_safe("Escaneie com a câmera"), align='C')

    pdf_bytes = bytearray(pdf.output())
    return send_file(io.BytesIO(pdf_bytes), download_name=f"Laudo_Doutor_Caixa_{cnpj}.pdf", as_attachment=True, mimetype='application/pdf')


if __name__ == '__main__':
    app.run(debug=True, port=5000)