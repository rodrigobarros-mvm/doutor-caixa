WHATSAPP_CONSULTOR = os.environ.get("WHATSAPP_CONSULTOR", "5581979091165").strip()
AGENDA_URL = os.environ.get("AGENDA_URL", "https://cal.com").strip()
PAINEL_SENHA = os.environ.get("PAINEL_SENHA", "maqtrak2026").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "9209744162:AAE-Yg8v1EBtifwf1LnF6gQSLf8kDbtkhuQ").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7635246193").strip()
import os
import json
import sqlite3
import threading
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template_string, request, redirect, url_for, make_response, jsonify

app = Flask(__name__)

# ==============================================================================
# CONFIGURAÇÕES E VARIÁVEIS DE AMBIENTE (RENDER)
# ==============================================================================
DB_PATH = os.environ.get("DB_PATH", "doutor_caixa.db")
WHATSAPP_CONSULTOR = os.environ.get("WHATSAPP_CONSULTOR", "5581999999999")  # Coloque seu número com 55 + DDD
AGENDA_URL = os.environ.get("AGENDA_URL", "https://cal.com")  # Seu link do Cal.com ou Calendly
PAINEL_SENHA = os.environ.get("PAINEL_SENHA", "maqtrak2026")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

FUSO_BR = timezone(timedelta(hours=-3))


def agora_br():
    return datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M")


# ==============================================================================
# BANCO DE DADOS (SQLITE + MIGRAÇÃO AUTOMÁTICA + SYNC OPCIONAL SUPABASE)
# ==============================================================================
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj TEXT UNIQUE,
            empresa TEXT,
            cidade TEXT,
            uf TEXT,
            cnae TEXT,
            ramo TEXT,
            solicitante TEXT,
            cargo TEXT,
            whatsapp TEXT,
            faturamento REAL,
            margem REAL,
            custos_fixos REAL,
            ticket_medio REAL,
            leads_mes REAL,
            taxa_conv REAL,
            vendedores REAL,
            meta_fat REAL,
            ponto_equilibrio REAL,
            lucro_atual REAL,
            potencial_oculto REAL,
            qtd_cegas INTEGER DEFAULT 0,
            pontos_cegos_json TEXT,
            diagnostico_json TEXT,
            status_crm TEXT DEFAULT 'Novo',
            completo INTEGER DEFAULT 0,
            clicou_cta INTEGER DEFAULT 0,
            data_cta TEXT,
            origem TEXT,
            criado_em TEXT,
            atualizado_em TEXT
        )
    """)

    # Migração segura caso a tabela já exista de versões anteriores
    colunas_novas = [
        ("cidade", "TEXT"),
        ("uf", "TEXT"),
        ("cnae", "TEXT"),
        ("ramo", "TEXT"),
        ("solicitante", "TEXT"),
        ("cargo", "TEXT"),
        ("whatsapp", "TEXT"),
        ("faturamento", "REAL"),
        ("margem", "REAL"),
        ("custos_fixos", "REAL"),
        ("ticket_medio", "REAL"),
        ("leads_mes", "REAL"),
        ("taxa_conv", "REAL"),
        ("vendedores", "REAL"),
        ("meta_fat", "REAL"),
        ("ponto_equilibrio", "REAL"),
        ("lucro_atual", "REAL"),
        ("potencial_oculto", "REAL"),
        ("qtd_cegas", "INTEGER DEFAULT 0"),
        ("pontos_cegos_json", "TEXT"),
        ("diagnostico_json", "TEXT"),
        ("status_crm", "TEXT DEFAULT 'Novo'"),
        ("completo", "INTEGER DEFAULT 0"),
        ("clicou_cta", "INTEGER DEFAULT 0"),
        ("data_cta", "TEXT"),
        ("origem", "TEXT"),
        ("criado_em", "TEXT"),
        ("atualizado_em", "TEXT"),
    ]
    for col, tipo in colunas_novas:
        try:
            cur.execute(f"ALTER TABLE leads ADD COLUMN {col} {tipo}")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()


init_db()


def sync_supabase_async(payload: dict):
    """Sincroniza o lead no Supabase em segundo plano se as chaves estiverem configuradas."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return

    def _run():
        try:
            url = f"{SUPABASE_URL}/rest/v1/leads?on_conflict=cnpj"
            headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates"
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            urllib.request.urlopen(req, timeout=6)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def enviar_telegram_async(mensagem: str):
    """Envia alerta instantâneo no Telegram sem travar a navegação do usuário."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    def _run():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": mensagem,
                "parse_mode": "HTML"
            }).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            urllib.request.urlopen(req, timeout=6)
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


# ==============================================================================
# FORMATAÇÃO E INTELIGÊNCIA SETORIAL (CNAE + BENCHMARKS)
# ==============================================================================
def limpar_cnpj(cnpj: str) -> str:
    return "".join(filter(str.isdigit, str(cnpj or "")))[:14]


def formatar_cnpj(cnpj: str) -> str:
    d = limpar_cnpj(cnpj)
    if len(d) != 14:
        return cnpj or ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def parse_float_opcional(valor):
    """Converte string monetária/percentual BR para float ou retorna None se vazio."""
    if valor is None:
        return None
    s = str(valor).strip()
    if not s:
        return None
    s = s.replace("R$", "").replace("%", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def fmt_moeda(valor) -> str:
    if valor is None:
        return "Não informado"
    neg = valor < 0
    v = abs(float(valor))
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-R$ {s}" if neg else f"R$ {s}"


def fmt_num(valor) -> str:
    if valor is None:
        return "0"
    return f"{int(round(float(valor))):,}".replace(",", ".")


app.jinja_env.filters["moeda"] = fmt_moeda
app.jinja_env.filters["num"] = fmt_num
app.jinja_env.filters["cnpj_fmt"] = formatar_cnpj


def obter_benchmark_setorial(cnae: str, ramo: str) -> dict:
    texto = f"{cnae or ''} {ramo or ''}".lower()

    if any(k in texto for k in ["saúde", "clínica", "médic", "odont", "estética", "hospital", "laborat"]):
        return {
            "segmento": "Saúde, Clínicas & Estética",
            "margem_bench": 52.0,
            "conv_bench": 28.0,
            "rotina_bench": "30 contatos ativos/dia e confirmação D-1 de agenda",
            "alerta": "Clínicas de alta performance protegem margem acima de 52% e convertem quase 1 a cada 3 avaliações agendadas."
        }
    if any(k in texto for k in ["software", "saas", "tecnologia", "ti", "informática", "agência", "marketing", "consultoria", "serviço", "b2b"]):
        return {
            "segmento": "Serviços B2B, Agências & Tecnologia",
            "margem_bench": 58.0,
            "conv_bench": 22.0,
            "rotina_bench": "20 visitas/reuniões por semana e 30 prospecções/dia",
            "alerta": "Operações B2B líderes operam com margem de contribuição acima de 58% e taxa de fechamento de 22% sobre propostas enviadas."
        }
    if any(k in texto for k in ["indústria", "fabric", "metal", "máquina", "equipamento", "engenharia", "construção"]):
        return {
            "segmento": "Indústria, Máquinas & Bens de Capital",
            "margem_bench": 34.0,
            "conv_bench": 18.0,
            "rotina_bench": "20 visitas técnicas semanais e follow-up estruturado de cotações",
            "alerta": "Empresas industriais e de bens de capital referência mantêm margem acima de 34% e conversão de 18% no pipeline técnico."
        }
    if any(k in texto for k in ["recorrência", "assinatura", "educação", "escola", "academia", "telecom", "segurança"]):
        return {
            "segmento": "Receita Recorrente & Assinaturas",
            "margem_bench": 62.0,
            "conv_bench": 25.0,
            "rotina_bench": "30 contatos/dia com foco em LTV e retenção mensal",
            "alerta": "Negócios recorrentes saudáveis operam com margem acima de 62% e retenção superior a 95% ao mês."
        }
    # Padrão: Comércio / Varejo / Distribuição
    return {
        "segmento": "Comércio, Varejo & Distribuição",
        "margem_bench": 32.0,
        "conv_bench": 24.0,
        "rotina_bench": "30 abordagens/dia na carteira ativa e giro semanal de estoque",
        "alerta": "Distribuidoras e varejistas de alta performance operam com margem de contribuição acima de 32% e conversão de 24% no atendimento."
    }


def processar_diagnostico(dados: dict) -> dict:
    """
    Calcula ponto de equilíbrio, lucro estimado, dinheiro deixado na mesa e pontos cegos.
    Trata campos vazios como indicadores não monitorados (pontos cegos de gestão).
    """
    fat = dados.get("faturamento")
    margem = dados.get("margem")
    fixos = dados.get("custos_fixos")
    ticket = dados.get("ticket_medio")
    leads_mes = dados.get("leads_mes")
    taxa_conv = dados.get("taxa_conv")
    vendedores = dados.get("vendedores")
    meta_fat = dados.get("meta_fat")

    bench = obter_benchmark_setorial(dados.get("cnae", ""), dados.get("ramo", ""))
    pontos_cegos = []

    # 1. Auditoria de Visibilidade dos Dados (O que o empresário NÃO soube informar)
    if fat is None:
        pontos_cegos.append({
            "titulo": "Faturamento Mensal Não Informado",
            "severidade": "CRÍTICO",
            "descricao": "Sem visibilidade exata da receita mensal, qualquer meta de crescimento ou corte de custos vira chute."
        })
    if margem is None:
        pontos_cegos.append({
            "titulo": "Margem de Contribuição Desconhecida (Gestão no Escuro)",
            "severidade": "CRÍTICO",
            "descricao": f"Você não soube informar sua margem líquida. Usamos {bench['margem_bench']:.0f}% (média do setor) como referência, mas vender sem saber a margem real é a causa nº 1 de empresas que faturam alto e quebram sem caixa."
        })
    if fixos is None:
        pontos_cegos.append({
            "titulo": "Custos Fixos Mensais Não Mapeados",
            "severidade": "ALTO",
            "descricao": "Sem conhecer o custo fixo total da estrutura, você não sabe em qual dia do mês a empresa começa a dar lucro."
        })
    if leads_mes is None or taxa_conv is None:
        pontos_cegos.append({
            "titulo": "Funil Comercial Sem Previsibilidade (Leads / Conversão)",
            "severidade": "ALTO",
            "descricao": "Faltam métricas de entrada de oportunidades ou taxa de fechamento. Sem medir o funil, o faturamento fica refém da sorte."
        })
    if ticket is None:
        pontos_cegos.append({
            "titulo": "Ticket Médio Não Monitorado",
            "severidade": "MÉDIO",
            "descricao": "Sem acompanhar o ticket médio, a equipe comercial tende a dar descontos excessivos para fechar pedidos."
        })

    # Valores efetivos para projeção matemática (usando benchmark conservador quando omitido)
    margem_calc = margem if (margem is not None and margem > 0) else bench["margem_bench"]
    margem_dec = margem_calc / 100.0

    # 2. Ponto de Equilíbrio e Lucro Operacional
    ponto_equilibrio = None
    lucro_atual = None
    folga_caixa_pct = None

    if fixos is not None and fixos > 0 and margem_dec > 0:
        ponto_equilibrio = fixos / margem_dec

    if fat is not None and fixos is not None:
        margem_bruta_rs = fat * margem_dec
        lucro_atual = margem_bruta_rs - fixos
        if ponto_equilibrio and ponto_equilibrio > 0:
            folga_caixa_pct = ((fat - ponto_equilibrio) / ponto_equilibrio) * 100.0

    # Alertas matemáticos se os números foram informados
    if lucro_atual is not None and lucro_atual < 0:
        pontos_cegos.insert(0, {
            "titulo": f"Hemorragia de Caixa: Déficit Estimado de {fmt_moeda(abs(lucro_atual))}/mês",
            "severidade": "CRÍTICO",
            "descricao": f"Com a margem atual de {margem_calc:.1f}%, o faturamento não cobre os custos fixos de {fmt_moeda(fixos)}. A operação está queimando caixa todos os meses."
        })
    elif folga_caixa_pct is not None and folga_caixa_pct < 12:
        pontos_cegos.append({
            "titulo": f"Margem de Segurança Estreita ({folga_caixa_pct:.1f}% acima do empate)",
            "severidade": "ALTO",
            "descricao": "Qualquer queda leve nas vendas ou atraso de recebimento joga o caixa imediatamente para o vermelho."
        })

    if margem is not None and margem < (bench["margem_bench"] - 5):
        pontos_cegos.append({
            "titulo": f"Margem Abaixo do Setor ({margem:.1f}% vs {bench['margem_bench']:.0f}% benchmark)",
            "severidade": "ALTO",
            "descricao": "Sua margem está comprimida frente aos concorrentes de alta performance — sinal de precificação defasada, descontos sem critério ou custo variável alto."
        })

    if taxa_conv is not None and taxa_conv < (bench["conv_bench"] - 4):
        pontos_cegos.append({
            "titulo": f"Conversão Comercial Baixa ({taxa_conv:.1f}% vs {bench['conv_bench']:.0f}% benchmark)",
            "severidade": "ALTO",
            "descricao": "Você está pagando para gerar oportunidades e perdendo vendas no acompanhamento (follow-up) ou abordagem."
        })

    # 3. Cálculo de Dinheiro Deixado na Mesa (Potencial Oculto Mensal)
    potencial_oculto = 0.0
    if fat is not None and fat > 0 and margem is not None and margem < bench["margem_bench"]:
        potencial_oculto += fat * ((bench["margem_bench"] - margem) / 100.0)

    if leads_mes is not None and leads_mes > 0 and taxa_conv is not None and taxa_conv < bench["conv_bench"]:
        tk_ref = ticket if (ticket is not None and ticket > 0) else (
            (fat / max(leads_mes * (taxa_conv / 100.0), 1)) if (fat and taxa_conv > 0) else 1500.0
        )
        vendas_extras = leads_mes * ((bench["conv_bench"] - taxa_conv) / 100.0)
        potencial_oculto += vendas_extras * tk_ref

    # Se não deu para calcular gap direto por falta de dados, estima 18% de ganho de eficiência sobre o faturamento (ou R$ 15.000 base)
    if potencial_oculto <= 0:
        if fat is not None and fat > 0:
            potencial_oculto = fat * 0.18
        else:
            potencial_oculto = 15000.0

    # 4. Meta Sugerida e Plano Diário da Equipe
    if meta_fat is None or meta_fat <= 0:
        if ponto_equilibrio and fat:
            meta_fat = max(fat * 1.25, ponto_equilibrio * 1.20)
        elif fat:
            meta_fat = fat * 1.25
        elif ponto_equilibrio:
            meta_fat = ponto_equilibrio * 1.20
        else:
            meta_fat = 100000.0

    eq_vendedores = int(vendedores) if (vendedores is not None and vendedores >= 1) else 1
    tk_calc = ticket if (ticket is not None and ticket > 0) else 2500.0
    conv_calc = (taxa_conv / 100.0) if (taxa_conv is not None and taxa_conv > 0) else (bench["conv_bench"] / 100.0)

    vendas_necessarias_mes = meta_fat / tk_calc
    oportunidades_mes = vendas_necessarias_mes / max(conv_calc, 0.05)
    contatos_dia_por_vendedor = max(30, int(round((oportunidades_mes * 3) / (22 * eq_vendedores))))
    visitas_semana_por_vendedor = max(20, int(round((oportunidades_mes / 4.3) / eq_vendedores)))

    # 5. Definição do CTA Dinâmico (Gatilho de Conversão)
    qtd_cegas = len(pontos_cegos)
    empresa_nome = dados.get("empresa") or "minha empresa"

    if lucro_atual is not None and lucro_atual < 0:
        cta_texto = f"🚨 Estancar Prejuízo de {fmt_moeda(abs(lucro_atual))}/mês Agora"
        cta_cor = "danger"
        wpp_msg = (
            f"Olá! Fiz o diagnóstico da *{empresa_nome}* no Doutor Caixa e apontou um déficit estimado de "
            f"*{fmt_moeda(abs(lucro_atual))}/mês* ({qtd_cegas} pontos cegos). Quero agendar a sessão de 20 min para estancar esse prejuízo."
        )
    elif qtd_cegas >= 2:
        cta_texto = f"🔍 Destravar Meus {qtd_cegas} Pontos Cegos Agora"
        cta_cor = "warning"
        wpp_msg = (
            f"Olá! Acabei de gerar o laudo da *{empresa_nome}* no Doutor Caixa e identificamos *{qtd_cegas} pontos cegos* "
            f"com potencial oculto de *{fmt_moeda(potencial_oculto)}/mês*. Quero agendar minha Sessão Estratégica de 20 min."
        )
    else:
        cta_texto = f"🚀 Desenhar Plano para Bater {fmt_moeda(meta_fat)}/mês"
        cta_cor = "success"
        wpp_msg = (
            f"Olá! Fiz o diagnóstico da *{empresa_nome}* no Doutor Caixa e quero desenhar o plano comercial e de caixa "
            f"para bater *{fmt_moeda(meta_fat)}/mês*."
        )

    return {
        "bench": bench,
        "margem_usada": round(margem_calc, 1),
        "margem_foi_estimada": margem is None,
        "ponto_equilibrio": round(ponto_equilibrio, 2) if ponto_equilibrio is not None else None,
        "lucro_atual": round(lucro_atual, 2) if lucro_atual is not None else None,
        "folga_caixa_pct": round(folga_caixa_pct, 1) if folga_caixa_pct is not None else None,
        "potencial_oculto": round(potencial_oculto, 2),
        "meta_fat": round(meta_fat, 2),
        "vendas_necessarias_mes": int(round(vendas_necessarias_mes)),
        "oportunidades_mes": int(round(oportunidades_mes)),
        "contatos_dia_por_vendedor": contatos_dia_por_vendedor,
        "visitas_semana_por_vendedor": visitas_semana_por_vendedor,
        "qtd_cegas": qtd_cegas,
        "pontos_cegos": pontos_cegos,
        "cta_texto": cta_texto,
        "cta_cor": cta_cor,
        "wpp_msg": wpp_msg
    }


# ==============================================================================
# ROTAS DE API (CONSULTA CNPJ, LEAD PARCIAL, STATUS CRM)
# ==============================================================================
@app.route("/api/cnpj/<cnpj>")
def api_consultar_cnpj(cnpj):
    cnpj_limpo = limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return jsonify({"ok": False, "erro": "CNPJ inválido"}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DoutorCaixa/7.0)",
        "Accept": "application/json"
    }

    # 1. BrasilAPI
    try:
        req = urllib.request.Request(f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            nome = (data.get("nome_fantasia") or "").strip() or (data.get("razao_social") or "").strip()
            if nome:
                return jsonify({
                    "ok": True,
                    "nome": nome,
                    "municipio": (data.get("municipio") or "").strip(),
                    "uf": (data.get("uf") or "").strip(),
                    "cnae": (data.get("cnae_fiscal_descricao") or "").strip()
                })
    except Exception:
        pass

    # 2. Fallback: Minha Receita
    try:
        req = urllib.request.Request(f"https://minhareceita.org/{cnpj_limpo}", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            nome = (data.get("nome_fantasia") or "").strip() or (data.get("razao_social") or "").strip()
            if nome:
                return jsonify({
                    "ok": True,
                    "nome": nome,
                    "municipio": (data.get("municipio") or "").strip(),
                    "uf": (data.get("uf") or "").strip(),
                    "cnae": (data.get("cnae_fiscal_descricao") or "").strip()
                })
    except Exception:
        pass

    # 3. Fallback: CNPJ.ws
    try:
        req = urllib.request.Request(f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}", headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            est = data.get("estabelecimento") or {}
            nome = (est.get("nome_fantasia") or "").strip() or (data.get("razao_social") or "").strip()
            cidade = (est.get("cidade") or {}).get("nome", "").strip()
            uf = (est.get("estado") or {}).get("sigla", "").strip()
            cnae = (est.get("atividade_principal") or {}).get("descricao", "").strip()
            if nome:
                return jsonify({
                    "ok": True,
                    "nome": nome,
                    "municipio": cidade,
                    "uf": uf,
                    "cnae": cnae
                })
    except Exception:
        pass

    return jsonify({"ok": False, "erro": "Não encontrado nas bases públicas"}), 404


@app.route("/api/lead-parcial", methods=["POST"])
def api_lead_parcial():
    """Captura silenciosa ao avançar da Etapa 1 para Etapa 2."""
    body = request.get_json(silent=True) or {}
    cnpj = limpar_cnpj(body.get("cnpj", ""))
    empresa = (body.get("empresa") or "").strip()
    if len(cnpj) != 14 or not empresa:
        return jsonify({"ok": False}), 400

    cidade = (body.get("cidade") or "").strip()
    uf = (body.get("uf") or "").strip()
    cnae = (body.get("cnae") or "").strip()
    ramo = (body.get("ramo") or "").strip()
    origem = (body.get("origem") or "Direto").strip()
    ts = agora_br()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, completo, status_crm FROM leads WHERE cnpj = ?", (cnpj,))
    existente = cur.fetchone()

    if existente:
        # Só atualiza dados básicos se ainda não finalizou o diagnóstico completo
        if not existente["completo"]:
            cur.execute("""
                UPDATE leads
                SET empresa = ?, cidade = ?, uf = ?, cnae = ?, ramo = ?, atualizado_em = ?
                WHERE cnpj = ?
            """, (empresa, cidade, uf, cnae, ramo, ts, cnpj))
    else:
        cur.execute("""
            INSERT INTO leads (cnpj, empresa, cidade, uf, cnae, ramo, status_crm, completo, origem, criado_em, atualizado_em)
            VALUES (?, ?, ?, ?, ?, ?, 'Lead Incompleto', 0, ?, ?, ?)
        """, (cnpj, empresa, cidade, uf, cnae, ramo, origem, ts, ts))

    conn.commit()
    conn.close()

    sync_supabase_async({
        "cnpj": cnpj,
        "empresa": empresa,
        "cidade": cidade,
        "uf": uf,
        "cnae": cnae,
        "ramo": ramo,
        "status_crm": existente["status_crm"] if existente else "Lead Incompleto",
        "completo": bool(existente["completo"]) if existente else False,
        "origem": origem,
        "atualizado_em": ts
    })

    return jsonify({"ok": True})


@app.route("/api/lead-status", methods=["POST"])
def api_lead_status():
    """Atualiza etapa do Mini-CRM direto do /painel."""
    if request.cookies.get("painel_auth") != PAINEL_SENHA:
        return jsonify({"ok": False, "erro": "Não autorizado"}), 401

    body = request.get_json(silent=True) or {}
    cnpj = limpar_cnpj(body.get("cnpj", ""))
    novo_status = (body.get("status") or "").strip()
    status_validos = [
        "Lead Incompleto",
        "Novo",
        "Contatado",
        "Reunião Agendada",
        "Proposta Enviada",
        "Fechado",
        "Perdido"
    ]
    if not cnpj or novo_status not in status_validos:
        return jsonify({"ok": False, "erro": "Dados inválidos"}), 400

    ts = agora_br()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE leads SET status_crm = ?, atualizado_em = ? WHERE cnpj = ?", (novo_status, ts, cnpj))
    conn.commit()
    conn.close()

    sync_supabase_async({"cnpj": cnpj, "status_crm": novo_status, "atualizado_em": ts})
    return jsonify({"ok": True})


# ==============================================================================
# ROTAS DE RASTREAMENTO DE CONVERSÃO (TELEGRAM ALERTA QUENTE + REDIRECT)
# ==============================================================================
@app.route("/cta-wpp/<cnpj>")
def cta_whatsapp(cnpj):
    cnpj_limpo = limpar_cnpj(cnpj)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM leads WHERE cnpj = ?", (cnpj_limpo,))
    lead = cur.fetchone()

    ts = agora_br()
    wpp_msg = "Olá! Fiz meu diagnóstico no Doutor Caixa e quero falar com um especialista."

    if lead:
        cur.execute("UPDATE leads SET clicou_cta = 1, data_cta = ?, atualizado_em = ? WHERE cnpj = ?", (ts, ts, cnpj_limpo))
        conn.commit()

        diag = json.loads(lead["diagnostico_json"] or "{}")
        if diag.get("wpp_msg"):
            wpp_msg = diag["wpp_msg"]

        alerta = (
            f"🔥 <b>ALERTA QUENTE — CLIQUE NO WHATSAPP!</b>\n\n"
            f"🏢 <b>Empresa:</b> {lead['empresa']} ({formatar_cnpj(cnpj_limpo)})\n"
            f"📍 <b>Local:</b> {lead['cidade'] or '-'}/{lead['uf'] or '-'}\n"
            f"👤 <b>Contato:</b> {lead['solicitante'] or '-'} ({lead['cargo'] or '-'})\n"
            f"📱 <b>WhatsApp:</b> {lead['whatsapp'] or '-'}\n"
            f"🚨 <b>Pontos Cegos:</b> {lead['qtd_cegas'] or 0}\n"
            f"💰 <b>Potencial Oculto:</b> {fmt_moeda(lead['potencial_oculto'])}\n\n"
            f"⚡ <i>Ele acabou de clicar no botão do laudo agora ({ts}). Chame nos próximos 2 minutos!</i>"
        )
        enviar_telegram_async(alerta)

    conn.close()
    wpp_destino = "".join(filter(str.isdigit, WHATSAPP_CONSULTOR))
    url_final = f"https://wa.me/{wpp_destino}?text={urllib.parse.quote(wpp_msg)}"
    return redirect(url_final, code=302)


@app.route("/cta-agenda/<cnpj>")
def cta_agenda(cnpj):
    cnpj_limpo = limpar_cnpj(cnpj)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM leads WHERE cnpj = ?", (cnpj_limpo,))
    lead = cur.fetchone()

    ts = agora_br()
    if lead:
        cur.execute("UPDATE leads SET clicou_cta = 1, data_cta = ?, atualizado_em = ? WHERE cnpj = ?", (ts, ts, cnpj_limpo))
        conn.commit()

        alerta = (
            f"📅 <b>ALERTA QUENTE — ABRIU AGENDA DIRETA!</b>\n\n"
            f"🏢 <b>Empresa:</b> {lead['empresa']} ({formatar_cnpj(cnpj_limpo)})\n"
            f"👤 <b>Contato:</b> {lead['solicitante'] or '-'} ({lead['cargo'] or '-'})\n"
            f"📱 <b>WhatsApp:</b> {lead['whatsapp'] or '-'}\n"
            f"⏰ <b>Horário:</b> {ts}"
        )
        enviar_telegram_async(alerta)

    conn.close()
    return redirect(AGENDA_URL, code=302)


# ==============================================================================
# ROTA PRINCIPAL (FORMULÁRIO MULTI-ETAPAS) E LAUDO EXECUTIVO
# ==============================================================================
@app.route("/", methods=["GET"])
def index():
    origem = request.args.get("utm_source") or request.args.get("src") or "Direto"
    return render_template_string(TEMPLATE_DIAGNOSTICO, origem=origem)


@app.route("/gerar-laudo", methods=["POST"])
def gerar_laudo():
    cnpj = limpar_cnpj(request.form.get("cnpj", ""))
    empresa = (request.form.get("empresa") or "").strip()
    cidade = (request.form.get("cidade") or "").strip()
    uf = (request.form.get("uf") or "").strip()
    cnae = (request.form.get("cnae") or "").strip()
    ramo = (request.form.get("ramo") or "Comércio / Varejo / Distribuição (Produtos)").strip()
    solicitante = (request.form.get("solicitante") or "").strip()
    cargo = (request.form.get("cargo") or "").strip()
    whatsapp = (request.form.get("whatsapp") or "").strip()
    origem = (request.form.get("origem") or "Direto").strip()

    if len(cnpj) != 14 or not empresa or not solicitante or not cargo or not whatsapp:
        return redirect(url_for("index"))

    dados = {
        "cnpj": cnpj,
        "empresa": empresa,
        "cidade": cidade,
        "uf": uf,
        "cnae": cnae,
        "ramo": ramo,
        "solicitante": solicitante,
        "cargo": cargo,
        "whatsapp": whatsapp,
        "faturamento": parse_float_opcional(request.form.get("faturamento")),
        "margem": parse_float_opcional(request.form.get("margem")),
        "custos_fixos": parse_float_opcional(request.form.get("custos_fixos")),
        "ticket_medio": parse_float_opcional(request.form.get("ticket_medio")),
        "leads_mes": parse_float_opcional(request.form.get("leads_mes")),
        "taxa_conv": parse_float_opcional(request.form.get("taxa_conv")),
        "vendedores": parse_float_opcional(request.form.get("vendedores")),
        "meta_fat": parse_float_opcional(request.form.get("meta_fat")),
    }

    diag = processar_diagnostico(dados)
    ts = agora_br()

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, status_crm FROM leads WHERE cnpj = ?", (cnpj,))
    existente = cur.fetchone()

    status_final = "Novo"
    if existente and existente["status_crm"] not in (None, "", "Lead Incompleto"):
        status_final = existente["status_crm"]

    if existente:
        cur.execute("""
            UPDATE leads SET
                empresa = ?, cidade = ?, uf = ?, cnae = ?, ramo = ?,
                solicitante = ?, cargo = ?, whatsapp = ?,
                faturamento = ?, margem = ?, custos_fixos = ?, ticket_medio = ?,
                leads_mes = ?, taxa_conv = ?, vendedores = ?, meta_fat = ?,
                ponto_equilibrio = ?, lucro_atual = ?, potencial_oculto = ?,
                qtd_cegas = ?, pontos_cegos_json = ?, diagnostico_json = ?,
                status_crm = ?, completo = 1, origem = ?, atualizado_em = ?
            WHERE cnpj = ?
        """, (
            empresa, cidade, uf, cnae, ramo,
            solicitante, cargo, whatsapp,
            dados["faturamento"], dados["margem"], dados["custos_fixos"], dados["ticket_medio"],
            dados["leads_mes"], dados["taxa_conv"], dados["vendedores"], diag["meta_fat"],
            diag["ponto_equilibrio"], diag["lucro_atual"], diag["potencial_oculto"],
            diag["qtd_cegas"], json.dumps(diag["pontos_cegos"], ensure_ascii=False),
            json.dumps(diag, ensure_ascii=False),
            status_final, origem, ts, cnpj
        ))
    else:
        cur.execute("""
            INSERT INTO leads (
                cnpj, empresa, cidade, uf, cnae, ramo,
                solicitante, cargo, whatsapp,
                faturamento, margem, custos_fixos, ticket_medio,
                leads_mes, taxa_conv, vendedores, meta_fat,
                ponto_equilibrio, lucro_atual, potencial_oculto,
                qtd_cegas, pontos_cegos_json, diagnostico_json,
                status_crm, completo, origem, criado_em, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (
            cnpj, empresa, cidade, uf, cnae, ramo,
            solicitante, cargo, whatsapp,
            dados["faturamento"], dados["margem"], dados["custos_fixos"], dados["ticket_medio"],
            dados["leads_mes"], dados["taxa_conv"], dados["vendedores"], diag["meta_fat"],
            diag["ponto_equilibrio"], diag["lucro_atual"], diag["potencial_oculto"],
            diag["qtd_cegas"], json.dumps(diag["pontos_cegos"], ensure_ascii=False),
            json.dumps(diag, ensure_ascii=False),
            status_final, origem, ts, ts
        ))

    conn.commit()
    conn.close()

    sync_supabase_async({
        "cnpj": cnpj,
        "empresa": empresa,
        "cidade": cidade,
        "uf": uf,
        "cnae": cnae,
        "ramo": ramo,
        "solicitante": solicitante,
        "cargo": cargo,
        "whatsapp": whatsapp,
        "faturamento": dados["faturamento"],
        "margem": dados["margem"],
        "custos_fixos": dados["custos_fixos"],
        "ponto_equilibrio": diag["ponto_equilibrio"],
        "lucro_atual": diag["lucro_atual"],
        "potencial_oculto": diag["potencial_oculto"],
        "qtd_cegas": diag["qtd_cegas"],
        "status_crm": status_final,
        "completo": True,
        "origem": origem,
        "atualizado_em": ts
    })

    alerta_novo = (
        f"✅ <b>NOVO DIAGNÓSTICO CONCLUÍDO!</b>\n\n"
        f"🏢 <b>Empresa:</b> {empresa}\n"
        f"📍 <b>Cidade/UF:</b> {cidade or '-'}/{uf or '-'}\n"
        f"👤 <b>Solicitante:</b> {solicitante} ({cargo})\n"
        f"📱 <b>WhatsApp:</b> {whatsapp}\n"
        f"💵 <b>Faturamento:</b> {fmt_moeda(dados['faturamento'])}\n"
        f"🚨 <b>Pontos Cegos:</b> {diag['qtd_cegas']}\n"
        f"💰 <b>Potencial Oculto:</b> {fmt_moeda(diag['potencial_oculto'])}/mês"
    )
    enviar_telegram_async(alerta_novo)

    return redirect(url_for("ver_laudo", cnpj=cnpj))


@app.route("/laudo/<cnpj>")
def ver_laudo(cnpj):
    cnpj_limpo = limpar_cnpj(cnpj)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM leads WHERE cnpj = ?", (cnpj_limpo,))
    lead = cur.fetchone()
    conn.close()

    if not lead:
        return redirect(url_for("index"))

    dados = dict(lead)
    diag = json.loads(dados.get("diagnostico_json") or "{}")
    if not diag:
        diag = processar_diagnostico(dados)

    # Calcula vagas restantes simuladas/reais na semana (máx 4 empresas/semana na Grande Recife)
    vagas_restantes = 2
    return render_template_string(
        TEMPLATE_LAUDO,
        lead=dados,
        diag=diag,
        vagas_restantes=vagas_restantes
    )


# ==============================================================================
# PAINEL ADMINISTRATIVO (MINI-CRM + LEADS INCOMPLETOS + INDICADORES)
# ==============================================================================
@app.route("/painel", methods=["GET", "POST"])
def painel():
    erro_login = ""
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if senha == PAINEL_SENHA:
            resp = make_response(redirect(url_for("painel")))
            resp.set_cookie("painel_auth", PAINEL_SENHA, max_age=86400 * 7, httponly=True)
            return resp
        erro_login = "Senha incorreta."

    if request.cookies.get("painel_auth") != PAINEL_SENHA:
        return render_template_string(TEMPLATE_LOGIN_PAINEL, erro=erro_login)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM leads ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    total_leads = len(rows)
    completos = sum(1 for r in rows if r.get("completo"))
    incompletos = total_leads - completos
    cliques_cta = sum(1 for r in rows if r.get("clicou_cta"))
    reunioes = sum(1 for r in rows if r.get("status_crm") == "Reunião Agendada")

    return render_template_string(
        TEMPLATE_PAINEL,
        leads=rows,
        stats={
            "total": total_leads,
            "completos": completos,
            "incompletos": incompletos,
            "cliques_cta": cliques_cta,
            "reunioes": reunioes
        }
    )


@app.route("/painel/sair")
def painel_sair():
    resp = make_response(redirect(url_for("painel")))
    resp.delete_cookie("painel_auth")
    return resp


# ==============================================================================
# TEMPLATES HTML (UX DE ALTA CONVERSÃO)
# ==============================================================================
TEMPLATE_DIAGNOSTICO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa — Diagnóstico Financeiro e Comercial</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary: #00C853;
            --primary-dark: #00A645;
            --bg: #F1F6F3;
            --card: #FFFFFF;
            --text: #0F172A;
            --muted: #64748B;
            --border: #E2E8F0;
            --danger: #EF4444;
            --warning: #F59E0B;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: var(--text); min-height: 100vh; display: flex; justify-content: center; padding: 24px 14px; }
        .container { width: 100%; max-width: 540px; background: var(--card); border-radius: 20px; padding: 28px 24px; box-shadow: 0 12px 35px rgba(15, 23, 42, 0.06); border: 1px solid #E6EDE9; }
        .topbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .brand { display: flex; align-items: center; gap: 10px; }
        .brand-icon { width: 42px; height: 42px; border-radius: 12px; background: linear-gradient(135deg, #00D65B, #00A645); display: flex; align-items: center; justify-content: center; color: #fff; font-weight: 800; font-size: 20px; box-shadow: 0 4px 12px rgba(0,200,83,0.28); }
        .brand-name { font-weight: 800; font-size: 14px; line-height: 1.1; color: #00A645; letter-spacing: 0.4px; }
        .brand-name span { display: block; font-size: 11px; color: var(--muted); font-weight: 600; }
        .btn-sair { font-size: 13px; color: var(--muted); text-decoration: none; font-weight: 600; }

        .progress-header { display: flex; justify-content: space-between; font-size: 11px; font-weight: 800; color: var(--primary-dark); letter-spacing: 0.5px; margin-bottom: 8px; text-transform: uppercase; }
        .progress-track { width: 100%; height: 6px; background: #E2ECE6; border-radius: 99px; overflow: hidden; margin-bottom: 24px; }
        .progress-fill { height: 100%; background: var(--primary); width: 25%; transition: width 0.35s ease; border-radius: 99px; }

        .step { display: none; animation: fadeIn 0.25s ease; }
        .step.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

        h1 { font-size: 22px; font-weight: 800; color: var(--text); margin-bottom: 6px; }
        .subtitle { font-size: 14px; color: var(--muted); line-height: 1.5; margin-bottom: 20px; }

        .info-banner { background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 12px; padding: 12px 14px; font-size: 12.5px; color: #166534; line-height: 1.45; margin-bottom: 18px; }
        .info-banner strong { color: #14532D; }

        .field { margin-bottom: 16px; }
        label { display: flex; justify-content: space-between; align-items: center; font-size: 13px; font-weight: 700; color: #1E293B; margin-bottom: 6px; }
        .badge-req { font-size: 11px; color: #00A645; background: #DCFCE7; padding: 2px 7px; border-radius: 6px; font-weight: 700; }
        .badge-opt { font-size: 11px; color: #64748B; background: #F1F5F9; padding: 2px 7px; border-radius: 6px; font-weight: 600; }

        input, select { width: 100%; padding: 13px 14px; border-radius: 12px; border: 1.5px solid var(--border); font-size: 15px; color: var(--text); background: #fff; transition: all 0.2s; outline: none; }
        input:focus, select:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(0, 200, 83, 0.14); }
        input.input-erro { border-color: var(--danger); background: #FEF2F2; }

        .field-help { font-size: 12px; color: var(--muted); margin-top: 5px; line-height: 1.4; }
        .status-cnpj { font-size: 12.5px; font-weight: 600; margin-top: 6px; min-height: 18px; }
        .err-msg { font-size: 12px; color: var(--danger); font-weight: 600; margin-top: 4px; display: none; }
        .err-msg.visible { display: block; }

        .ramo-box { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; padding: 12px 14px; font-size: 12.5px; color: #334155; line-height: 1.45; margin-bottom: 20px; }

        /* Mini Calculadora de Margem */
        .calc-toggle { display: inline-flex; align-items: center; gap: 6px; margin-top: 7px; font-size: 12.5px; font-weight: 700; color: #00A645; background: #ECFDF5; border: 1px solid #A7F3D0; padding: 6px 11px; border-radius: 8px; cursor: pointer; }
        .calc-toggle:hover { background: #D1FAE5; }
        .calc-box { display: none; margin-top: 10px; background: #F8FAFC; border: 1.5px dashed #94A3B8; border-radius: 12px; padding: 14px; }
        .calc-box.open { display: block; }
        .calc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px; }
        .calc-box input { padding: 9px 11px; font-size: 13.5px; }
        .btn-aplicar-calc { margin-top: 10px; width: 100%; padding: 9px; border: none; border-radius: 9px; background: #0F172A; color: #fff; font-weight: 700; font-size: 13px; cursor: pointer; }

        /* Teaser Desfocado na Etapa 4 */
        .teaser-card { background: linear-gradient(135deg, #0F172A, #1E293B); color: #fff; border-radius: 16px; padding: 18px; margin-bottom: 20px; position: relative; overflow: hidden; }
        .teaser-badge { display: inline-block; background: rgba(0,200,83,0.2); color: #4ADE80; font-size: 11px; font-weight: 800; padding: 4px 10px; border-radius: 99px; margin-bottom: 10px; }
        .teaser-text { font-size: 13.5px; line-height: 1.5; color: #E2E8F0; margin-bottom: 14px; }
        .teaser-blur-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; position: relative; }
        .teaser-metric { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 10px; }
        .teaser-metric small { display: block; font-size: 11px; color: #94A3B8; margin-bottom: 4px; }
        .teaser-metric strong { font-size: 16px; color: #4ADE80; filter: blur(5px); user-select: none; display: inline-block; }
        .teaser-lock { text-align: center; font-size: 11.5px; color: #CBD5E1; margin-top: 10px; font-weight: 600; }

        .btn-row { display: flex; gap: 10px; margin-top: 8px; }
        .btn-primary { flex: 1; background: var(--primary); color: #fff; border: none; border-radius: 12px; padding: 15px 18px; font-size: 15.5px; font-weight: 800; cursor: pointer; transition: background 0.2s, transform 0.1s; box-shadow: 0 6px 18px rgba(0, 200, 83, 0.25); }
        .btn-primary:hover { background: var(--primary-dark); }
        .btn-primary:active { transform: scale(0.99); }
        .btn-back { background: #F1F5F9; color: #475569; border: none; border-radius: 12px; padding: 15px 16px; font-size: 14px; font-weight: 700; cursor: pointer; }

        .footer-lgpd { margin-top: 22px; padding-top: 16px; border-top: 1px solid #EEF2F0; text-align: center; font-size: 11.5px; color: var(--muted); line-height: 1.5; }
        .footer-lgpd .box-lgpd { background: #F8FAFC; border-radius: 10px; padding: 8px 12px; margin-bottom: 10px; }
    </style>
</head>
<body>
<div class="container">
    <div class="topbar">
        <div class="brand">
            <div class="brand-icon">📊</div>
            <div class="brand-name">DOUTOR<br>CAIXA</div>
        </div>
        <a href="/" class="btn-sair">✕ Sair</a>
    </div>

    <div class="progress-header">
        <span id="step-label">ETAPA 1 DE 4 — DADOS DA EMPRESA</span>
        <span id="step-pct">25%</span>
    </div>
    <div class="progress-track">
        <div class="progress-fill" id="progress-fill"></div>
    </div>

    <form id="form-diag" method="POST" action="/gerar-laudo" novalidate>
        <input type="hidden" name="cidade" id="inp_cidade">
        <input type="hidden" name="uf" id="inp_uf">
        <input type="hidden" name="cnae" id="inp_cnae">
        <input type="hidden" name="origem" id="inp_origem" value="{{ origem }}">

        <!-- ETAPA 1 -->
        <div class="step active" id="step-1">
            <h1>1. Dados da Empresa</h1>
            <p class="subtitle">Digite o CNPJ para localizarmos sua empresa automaticamente e calibrarmos o diagnóstico ao seu setor.</p>

            <div class="field">
                <label>CNPJ Válido (Somente números) <span class="badge-req">Obrigatório</span></label>
                <input type="text" id="cnpj" name="cnpj" placeholder="00.000.000/0000-00" maxlength="18" inputmode="numeric">
                <div class="status-cnpj" id="cnpj_status"></div>
                <div class="err-msg" id="err_cnpj">Informe um CNPJ válido com 14 dígitos.</div>
            </div>

            <div class="field">
                <label>Nome da Empresa <span class="badge-req">Obrigatório</span></label>
                <input type="text" id="empresa_nome" name="empresa" placeholder="Ex: Distribuidora Recife Ltda">
                <div class="err-msg" id="err_empresa_nome">Informe o nome da empresa.</div>
            </div>

            <div class="field">
                <label>Ramo de Atuação / Modelo de Venda</label>
                <select id="ramo" name="ramo">
                    <option value="Comércio / Varejo / Distribuição (Produtos)">Comércio / Varejo / Distribuição (Produtos)</option>
                    <option value="Serviços B2B / Consultoria / Agência / TI">Serviços B2B / Consultoria / Agência / TI</option>
                    <option value="Clínicas / Saúde / Estética">Clínicas / Saúde / Estética</option>
                    <option value="Indústria / Fábrica / Máquinas">Indústria / Fábrica / Máquinas</option>
                    <option value="Recorrência / SaaS / Assinaturas">Recorrência / SaaS / Assinaturas</option>
                </select>
            </div>

            <div class="ramo-box" id="ramo-desc">
                🛒 <strong>Comércio e Varejo:</strong> Como cada mês começa sem contratos fixos garantidos, nosso cálculo vai focar em <strong>giro de estoque, movimento diário de loja/WhatsApp e proteção da margem</strong>.
            </div>

            <div class="btn-row">
                <button type="button" class="btn-primary" onclick="avancarEtapa1()">Avançar →</button>
            </div>
        </div>

        <!-- ETAPA 2 -->
        <div class="step" id="step-2">
            <h1>2. Raio-X Financeiro</h1>
            <p class="subtitle">Preencha o que você souber agora para calcularmos seu ponto de equilíbrio real.</p>

            <div class="info-banner">
                💡 <strong>Não sabe algum número de cabeça?</strong> Pode deixar o campo em branco! Vamos sinalizar esse indicador como um <strong>Ponto de Atenção no seu laudo</strong> para você saber exatamente onde está operando no escuro.
            </div>

            <div class="field">
                <label>Faturamento Mensal Médio (R$) <span class="badge-opt">Opcional</span></label>
                <input type="text" id="faturamento" name="faturamento" placeholder="Ex: 120.000,00" inputmode="decimal" class="mask-moeda">
                <div class="field-help">Média de vendas brutas nos últimos 3 meses.</div>
            </div>

            <div class="field">
                <label>Margem de Contribuição Média (%) <span class="badge-opt">Opcional</span></label>
                <input type="text" id="margem" name="margem" placeholder="Ex: 35" inputmode="decimal">
                <div class="field-help">Quanto sobra (%) de cada venda após pagar custo do produto/serviço, impostos e comissões.</div>

                <button type="button" class="calc-toggle" onclick="toggleCalcMargem()">🧮 Não sei minha margem % — Calcular em 10s</button>

                <div class="calc-box" id="calc-margem-box">
                    <div style="font-size:12px; font-weight:700; color:#1E293B;">Calculadora Rápida de Margem Líquida</div>
                    <div class="calc-grid">
                        <div>
                            <label style="font-size:11.5px;">Preço de Venda / Receita (R$)</label>
                            <input type="text" id="calc_preco" placeholder="Ex: 1.000,00" class="mask-moeda">
                        </div>
                        <div>
                            <label style="font-size:11.5px;">Custo Produto/Serviço (R$)</label>
                            <input type="text" id="calc_custo" placeholder="Ex: 550,00" class="mask-moeda">
                        </div>
                    </div>
                    <div style="margin-top:8px;">
                        <label style="font-size:11.5px;">Impostos + Comissões + Taxa Cartão (%)</label>
                        <input type="text" id="calc_imp" placeholder="Ex: 12" inputmode="decimal">
                    </div>
                    <button type="button" class="btn-aplicar-calc" onclick="aplicarCalculoMargem()">Calcular e Preencher Margem Automaticamente ✓</button>
                </div>
            </div>

            <div class="field">
                <label>Custos Fixos Mensais Totais (R$) <span class="badge-opt">Opcional</span></label>
                <input type="text" id="custos_fixos" name="custos_fixos" placeholder="Ex: 38.000,00" inputmode="decimal" class="mask-moeda">
                <div class="field-help">Soma de folha, pró-labore, aluguel, sistema, contabilidade e contas fixas (mesmo se vender zero).</div>
            </div>

            <div class="btn-row">
                <button type="button" class="btn-back" onclick="irParaEtapa(1)">← Voltar</button>
                <button type="button" class="btn-primary" onclick="irParaEtapa(3)">Avançar →</button>
            </div>
        </div>

        <!-- ETAPA 3 -->
        <div class="step" id="step-3">
            <h1>3. Motor Comercial & Metas</h1>
            <p class="subtitle">Vamos cruzar sua geração de oportunidades com a capacidade de fechamento do time.</p>

            <div class="info-banner">
                🎯 <strong>Dica:</strong> Se não controlar algum indicador comercial hoje, apenas deixe em branco e clique em avançar.
            </div>

            <div class="field">
                <label>Ticket Médio por Venda / Contrato (R$) <span class="badge-opt">Opcional</span></label>
                <input type="text" id="ticket_medio" name="ticket_medio" placeholder="Ex: 2.500,00" inputmode="decimal" class="mask-moeda">
                <div class="field-help">Valor médio de cada pedido ou contrato fechado.</div>
            </div>

            <div class="field">
                <label>Oportunidades / Orçamentos por Mês <span class="badge-opt">Opcional</span></label>
                <input type="number" id="leads_mes" name="leads_mes" placeholder="Ex: 80" inputmode="numeric">
                <div class="field-help">Quantos clientes pedem orçamento ou chegam no WhatsApp/loja por mês.</div>
            </div>

            <div class="field">
                <label>Taxa de Fechamento / Conversão (%) <span class="badge-opt">Opcional</span></label>
                <input type="text" id="taxa_conv" name="taxa_conv" placeholder="Ex: 20" inputmode="decimal">
                <div class="field-help">De cada 100 orçamentos enviados, quantos viram venda paga?</div>
            </div>

            <div class="field">
                <label>Tamanho da Equipe Comercial (Vendedores) <span class="badge-opt">Opcional</span></label>
                <input type="number" id="vendedores" name="vendedores" placeholder="Ex: 3" inputmode="numeric">
                <div class="field-help">Inclua você se você também atua nas vendas.</div>
            </div>

            <div class="field">
                <label>Meta de Faturamento Desejada (R$/mês) <span class="badge-opt">Opcional</span></label>
                <input type="text" id="meta_fat" name="meta_fat" placeholder="Ex: 180.000,00" inputmode="decimal" class="mask-moeda">
            </div>

            <div class="btn-row">
                <button type="button" class="btn-back" onclick="irParaEtapa(2)">← Voltar</button>
                <button type="button" class="btn-primary" onclick="prepararEtapa4()">Ver Meu Diagnóstico →</button>
            </div>
        </div>

        <!-- ETAPA 4 -->
        <div class="step" id="step-4">
            <h1>4. Liberar Laudo Completo</h1>
            <p class="subtitle">Seu diagnóstico executivo já foi processado. Preencha seus dados para desbloquear.</p>

            <!-- PRÉVIA DESFOCADA (TEASER) -->
            <div class="teaser-card">
                <div class="teaser-badge">⚡ DIAGNÓSTICO PRONTO</div>
                <div class="teaser-text" id="teaser-resumo">
                    ✅ Encontramos <strong>3 pontos cegos</strong> e calculamos o faturamento exato para empatar as contas da sua empresa.
                </div>
                <div class="teaser-blur-grid">
                    <div class="teaser-metric">
                        <small>Ponto de Equilíbrio</small>
                        <strong>R$ 84.500,00</strong>
                    </div>
                    <div class="teaser-metric">
                        <small>Potencial Oculto / Mês</small>
                        <strong>R$ 27.900,00</strong>
                    </div>
                </div>
                <div class="teaser-lock">🔒 Informe seu nome, cargo e WhatsApp abaixo para liberar o laudo</div>
            </div>

            <div class="field">
                <label>Seu Nome Completo <span class="badge-req">Obrigatório</span></label>
                <input type="text" id="solicitante" name="solicitante" placeholder="Ex: Carlos Eduardo Silva">
                <div class="err-msg" id="err_solicitante">Informe seu nome.</div>
            </div>

            <div class="field">
                <label>Seu Cargo na Empresa <span class="badge-req">Obrigatório</span></label>
                <select id="cargo" name="cargo">
                    <option value="">Selecione seu cargo...</option>
                    <option value="Sócio / Proprietário / CEO">Sócio / Proprietário / CEO</option>
                    <option value="Diretor Comercial / Geral">Diretor Comercial / Geral</option>
                    <option value="Gerente Comercial / Financeiro">Gerente Comercial / Financeiro</option>
                    <option value="Administrador / Gestor">Administrador / Gestor</option>
                </select>
                <div class="err-msg" id="err_cargo">Selecione seu cargo.</div>
            </div>

            <div class="field">
                <label>WhatsApp com DDD <span class="badge-req">Obrigatório</span></label>
                <input type="tel" id="whatsapp" name="whatsapp" placeholder="(81) 99999-9999" maxlength="15" inputmode="tel">
                <div class="err-msg" id="err_whatsapp">Informe um número de WhatsApp válido com DDD.</div>
            </div>

            <div class="btn-row">
                <button type="button" class="btn-back" onclick="irParaEtapa(3)">← Voltar</button>
                <button type="submit" class="btn-primary" onclick="return validarFinal()">🔓 Liberar Laudo Agora</button>
            </div>
        </div>
    </form>

    <div class="footer-lgpd">
        <div class="box-lgpd">
            🔒 <strong>Sigilo Garantido:</strong> Seus dados são confidenciais e protegidos pela LGPD.
        </div>
        Doutor Caixa é uma empresa da <strong>MaqTrak</strong> - Hub de Soluções em Inteligência de Mercado.
    </div>
</div>

<script>
    let ultimoCnpjBuscado = "";
    let nomeAutoPreenchido = false;

    const descricoesRamo = {
        "Comércio / Varejo / Distribuição (Produtos)": "🛒 <strong>Comércio e Varejo:</strong> Como cada mês começa sem contratos fixos garantidos, nosso cálculo vai focar em <strong>giro de estoque, movimento diário de loja/WhatsApp e proteção da margem</strong>.",
        "Serviços B2B / Consultoria / Agência / TI": "💼 <strong>Serviços B2B & Agências:</strong> Vamos calibrar seu diagnóstico para <strong>capacidade de entrega da equipe, margem por hora/projeto e previsibilidade de propostas</strong>.",
        "Clínicas / Saúde / Estética": "🩺 <strong>Saúde & Clínicas:</strong> Nosso modelo vai avaliar <strong>ocupação de agenda, conversão de avaliações e margem líquida por procedimento</strong>.",
        "Indústria / Fábrica / Máquinas": "🏭 <strong>Indústria & Máquinas:</strong> Vamos analisar <strong>absorção de custo fixo industrial, ciclo de negociação técnica e margem de contribuição</strong>.",
        "Recorrência / SaaS / Assinaturas": "🔄 <strong>Recorrência & Assinaturas:</strong> O foco será <strong>velocidade de aquisição (CAC), margem recorrente e expansão da base ativa</strong>."
    };

    document.getElementById('ramo').addEventListener('change', function(e) {
        document.getElementById('ramo-desc').innerHTML = descricoesRamo[e.target.value] || "";
    });

    function validarCNPJ(cnpj) {
        cnpj = cnpj.replace(/[^\d]+/g, '');
        if (cnpj.length !== 14 || /^(\d)\1+$/.test(cnpj)) return false;
        let tamanho = cnpj.length - 2;
        let numeros = cnpj.substring(0, tamanho);
        let digitos = cnpj.substring(tamanho);
        let soma = 0, pos = tamanho - 7;
        for (let i = tamanho; i >= 1; i--) {
            soma += numeros.charAt(tamanho - i) * pos--;
            if (pos < 2) pos = 9;
        }
        let resultado = soma % 11 < 2 ? 0 : 11 - soma % 11;
        if (resultado != digitos.charAt(0)) return false;
        tamanho += 1;
        numeros = cnpj.substring(0, tamanho);
        soma = 0; pos = tamanho - 7;
        for (let i = tamanho; i >= 1; i--) {
            soma += numeros.charAt(tamanho - i) * pos--;
            if (pos < 2) pos = 9;
        }
        resultado = soma % 11 < 2 ? 0 : 11 - soma % 11;
        return resultado == digitos.charAt(1);
    }

    async function consultarBrasilAPI(cnpjLimpo) {
        if (cnpjLimpo === ultimoCnpjBuscado) return;
        ultimoCnpjBuscado = cnpjLimpo;

        const statusEl = document.getElementById('cnpj_status');
        const nomeEl = document.getElementById('empresa_nome');
        statusEl.style.color = '#64748B';
        statusEl.innerText = '⏳ Localizando dados da empresa...';

        try {
            const resp = await fetch(`/api/cnpj/${cnpjLimpo}`);
            const data = await resp.json();
            if (!resp.ok || !data.ok) {
                ultimoCnpjBuscado = "";
                statusEl.style.color = '#64748B';
                statusEl.innerText = 'ℹ️ CNPJ válido. Informe o nome da empresa abaixo para continuar.';
                return;
            }

            const nomeOficial = (data.nome || '').trim();
            const municipio = (data.municipio || '').trim();
            const uf = (data.uf || '').trim();
            const cnae = (data.cnae || '').trim();

            if (nomeOficial && (!nomeEl.value.trim() || nomeAutoPreenchido)) {
                nomeEl.value = nomeOficial;
                nomeAutoPreenchido = true;
                nomeEl.classList.remove('input-erro');
                document.getElementById('err_empresa_nome').classList.remove('visible');
            }
            document.getElementById('inp_cidade').value = municipio;
            document.getElementById('inp_uf').value = uf;
            document.getElementById('inp_cnae').value = cnae;

            if (municipio && uf) {
                statusEl.style.color = '#00A645';
                statusEl.innerText = `✅ Empresa localizada em ${municipio}/${uf}`;
            } else if (nomeOficial) {
                statusEl.style.color = '#00A645';
                statusEl.innerText = '✅ Dados da empresa localizados!';
            }
        } catch (e) {
            ultimoCnpjBuscado = "";
            statusEl.style.color = '#64748B';
            statusEl.innerText = 'ℹ️ CNPJ válido. Preencha o nome da empresa abaixo.';
        }
    }

    const cnpjInput = document.getElementById('cnpj');
    cnpjInput.addEventListener('input', function(e) {
        let v = e.target.value.replace(/\D/g, '').slice(0, 14);
        v = v.replace(/^(\d{2})(\d)/, '$1.$2');
        v = v.replace(/^(\d{2})\.(\d{3})(\d)/, '$1.$2.$3');
        v = v.replace(/\.(\d{3})(\d)/, '.$1/$2');
        v = v.replace(/(\d{4})(\d)/, '$1-$2');
        e.target.value = v;

        let digits = v.replace(/\D/g, '');
        if (digits.length === 14 && validarCNPJ(digits)) {
            document.getElementById('err_cnpj').classList.remove('visible');
            cnpjInput.classList.remove('input-erro');
            consultarBrasilAPI(digits);
        }
    });

    cnpjInput.addEventListener('blur', function(e) {
        let digits = e.target.value.replace(/\D/g, '').slice(0, 14);
        if (digits.length === 14 && validarCNPJ(digits)) {
            consultarBrasilAPI(digits);
        }
    });

    document.getElementById('empresa_nome').addEventListener('input', function() {
        nomeAutoPreenchido = false;
    });

    // Máscara monetária BRL
    document.querySelectorAll('.mask-moeda').forEach(inp => {
        inp.addEventListener('input', function(e) {
            let v = e.target.value.replace(/\D/g, '');
            if (!v) { e.target.value = ''; return; }
            v = (parseInt(v, 10) / 100).toFixed(2) + '';
            v = v.replace('.', ',');
            v = v.replace(/(\d)(?=(\d{3})+(?!\d))/g, '$1.');
            e.target.value = v;
        });
    });

    // Máscara WhatsApp
    document.getElementById('whatsapp').addEventListener('input', function(e) {
        let v = e.target.value.replace(/\D/g, '').slice(0, 11);
        if (v.length > 6) {
            v = v.replace(/^(\d{2})(\d{5})(\d{0,4})/, '($1) $2-$3');
        } else if (v.length > 2) {
            v = v.replace(/^(\d{2})(\d{0,5})/, '($1) $2');
        }
        e.target.value = v;
    });

    function parseBRL(str) {
        if (!str) return null;
        let limpo = str.replace(/\./g, '').replace(',', '.').replace(/[^\d.-]/g, '');
        let n = parseFloat(limpo);
        return isNaN(n) ? null : n;
    }

    function toggleCalcMargem() {
        document.getElementById('calc-margem-box').classList.toggle('open');
    }

    function aplicarCalculoMargem() {
        const preco = parseBRL(document.getElementById('calc_preco').value);
        const custo = parseBRL(document.getElementById('calc_custo').value) || 0;
        const imp = parseBRL(document.getElementById('calc_imp').value) || 0;

        if (!preco || preco <= 0) {
            alert('Informe o Preço de Venda ou Receita para calcular.');
            return;
        }
        let margemBrutaPct = ((preco - custo) / preco) * 100;
        let margemLiquida = Math.max(1, margemBrutaPct - imp);
        document.getElementById('margem').value = margemLiquida.toFixed(1).replace('.', ',');
        document.getElementById('calc-margem-box').classList.remove('open');
    }

    function irParaEtapa(n) {
        document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
        document.getElementById(`step-${n}`).classList.add('active');

        const titulos = {
            1: ["ETAPA 1 DE 4 — DADOS DA EMPRESA", "25%"],
            2: ["ETAPA 2 DE 4 — RAIO-X FINANCEIRO", "50%"],
            3: ["ETAPA 3 DE 4 — MOTOR COMERCIAL", "75%"],
            4: ["ETAPA 4 DE 4 — LIBERAR LAUDO", "100%"]
        };
        document.getElementById('step-label').innerText = titulos[n][0];
        document.getElementById('step-pct').innerText = titulos[n][1];
        document.getElementById('progress-fill').style.width = titulos[n][1];
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }

    function avancarEtapa1() {
        const digits = document.getElementById('cnpj').value.replace(/\D/g, '');
        const empresa = document.getElementById('empresa_nome').value.trim();
        let ok = true;

        if (digits.length !== 14 || !validarCNPJ(digits)) {
            document.getElementById('cnpj').classList.add('input-erro');
            document.getElementById('err_cnpj').classList.add('visible');
            ok = false;
        } else {
            document.getElementById('cnpj').classList.remove('input-erro');
            document.getElementById('err_cnpj').classList.remove('visible');
        }

        if (!empresa) {
            document.getElementById('empresa_nome').classList.add('input-erro');
            document.getElementById('err_empresa_nome').classList.add('visible');
            ok = false;
        } else {
            document.getElementById('empresa_nome').classList.remove('input-erro');
            document.getElementById('err_empresa_nome').classList.remove('visible');
        }

        if (!ok) return;

        // Captura silenciosa em segundo plano (Lead Parcial)
        fetch('/api/lead-parcial', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                cnpj: digits,
                empresa: empresa,
                cidade: document.getElementById('inp_cidade').value,
                uf: document.getElementById('inp_uf').value,
                cnae: document.getElementById('inp_cnae').value,
                ramo: document.getElementById('ramo').value,
                origem: document.getElementById('inp_origem').value
            })
        }).catch(() => {});

        irParaEtapa(2);
    }

    function prepararEtapa4() {
        const empresa = document.getElementById('empresa_nome').value.trim() || "sua empresa";
        const campos = ['faturamento', 'margem', 'custos_fixos', 'ticket_medio', 'leads_mes', 'taxa_conv'];
        let vazios = 0;
        campos.forEach(id => {
            if (!document.getElementById(id).value.trim()) vazios++;
        });
        let cegasEstimadas = Math.max(2, vazios);

        document.getElementById('teaser-resumo').innerHTML =
            `✅ Encontramos <strong>${cegasEstimadas} pontos cegos</strong> e calculamos o faturamento exato para empatar as contas da <strong>${empresa}</strong>. Informe seu WhatsApp para liberar o laudo.`;

        irParaEtapa(4);
    }

    function validarFinal() {
        const sol = document.getElementById('solicitante').value.trim();
        const cargo = document.getElementById('cargo').value.trim();
        const wpp = document.getElementById('whatsapp').value.replace(/\D/g, '');
        let ok = true;

        if (!sol) {
            document.getElementById('solicitante').classList.add('input-erro');
            document.getElementById('err_solicitante').classList.add('visible');
            ok = false;
        } else {
            document.getElementById('solicitante').classList.remove('input-erro');
            document.getElementById('err_solicitante').classList.remove('visible');
        }

        if (!cargo) {
            document.getElementById('cargo').classList.add('input-erro');
            document.getElementById('err_cargo').classList.add('visible');
            ok = false;
        } else {
            document.getElementById('cargo').classList.remove('input-erro');
            document.getElementById('err_cargo').classList.remove('visible');
        }

        if (wpp.length < 10) {
            document.getElementById('whatsapp').classList.add('input-erro');
            document.getElementById('err_whatsapp').classList.add('visible');
            ok = false;
        } else {
            document.getElementById('whatsapp').classList.remove('input-erro');
            document.getElementById('err_whatsapp').classList.remove('visible');
        }

        return ok;
    }
</script>
</body>
</html>
"""


TEMPLATE_LAUDO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Laudo Executivo — {{ lead.empresa }} | Doutor Caixa</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: #F1F6F3; color: #0F172A; padding: 24px 14px 60px; }
        .wrap { max-width: 820px; margin: 0 auto; }

        .header-card { background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%); color: #fff; border-radius: 20px; padding: 28px; margin-bottom: 18px; box-shadow: 0 12px 30px rgba(15,23,42,0.12); }
        .top-meta { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
        .tag-brand { background: rgba(0,200,83,0.18); color: #4ADE80; font-weight: 800; font-size: 12px; padding: 5px 12px; border-radius: 99px; letter-spacing: 0.4px; }
        .btn-print { background: rgba(255,255,255,0.12); color: #fff; border: 1px solid rgba(255,255,255,0.2); padding: 7px 14px; border-radius: 10px; font-size: 12.5px; font-weight: 700; cursor: pointer; }
        .header-card h1 { font-size: 24px; font-weight: 800; margin-bottom: 6px; }
        .header-sub { font-size: 13.5px; color: #CBD5E1; line-height: 1.5; }

        .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 18px; }
        .kpi-card { background: #fff; border-radius: 16px; padding: 18px; border: 1px solid #E2E8F0; box-shadow: 0 4px 14px rgba(15,23,42,0.03); }
        .kpi-card small { display: block; font-size: 12px; font-weight: 700; color: #64748B; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.3px; }
        .kpi-val { font-size: 21px; font-weight: 800; color: #0F172A; }
        .kpi-val.green { color: #00A645; }
        .kpi-val.red { color: #DC2626; }
        .kpi-val.amber { color: #D97706; }
        .kpi-note { font-size: 11.5px; color: #64748B; margin-top: 5px; line-height: 1.35; }

        /* Benchmark Setorial CNAE */
        .bench-card { background: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 16px; padding: 18px 20px; margin-bottom: 18px; }
        .bench-title { font-size: 13px; font-weight: 800; color: #1D4ED8; text-transform: uppercase; letter-spacing: 0.4px; margin-bottom: 6px; }
        .bench-text { font-size: 14px; color: #1E3A8A; line-height: 1.55; }

        .section-card { background: #fff; border-radius: 18px; padding: 24px; border: 1px solid #E2E8F0; margin-bottom: 18px; box-shadow: 0 4px 16px rgba(15,23,42,0.03); }
        .section-title { font-size: 18px; font-weight: 800; color: #0F172A; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }

        .cega-item { border-left: 4px solid #EF4444; background: #FEF2F2; border-radius: 0 12px 12px 0; padding: 14px 16px; margin-bottom: 12px; }
        .cega-item.alto { border-left-color: #F59E0B; background: #FFFBEB; }
        .cega-item.medio { border-left-color: #3B82F6; background: #EFF6FF; }
        .cega-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 5px; }
        .cega-head strong { font-size: 14.5px; color: #0F172A; }
        .sev-badge { font-size: 10.5px; font-weight: 800; padding: 2px 8px; border-radius: 6px; background: #FEE2E2; color: #B91C1C; }
        .cega-item.alto .sev-badge { background: #FEF3C7; color: #B45309; }
        .cega-desc { font-size: 13.5px; color: #334155; line-height: 1.5; }

        /* Bloco de Oferta Sessão Estratégica (20 min) com Escassez Real */
        .offer-card { background: linear-gradient(135deg, #064E3B 0%, #0F172A 100%); color: #fff; border-radius: 20px; padding: 26px 24px; margin-bottom: 18px; border: 2px solid #00C853; box-shadow: 0 14px 32px rgba(0, 200, 83, 0.16); }
        .scarcity-pill { display: inline-block; background: #FEF08A; color: #854D0E; font-weight: 800; font-size: 12px; padding: 5px 12px; border-radius: 99px; margin-bottom: 12px; }
        .offer-card h2 { font-size: 21px; font-weight: 800; margin-bottom: 8px; line-height: 1.3; }
        .offer-sub { font-size: 14px; color: #CBD5E1; margin-bottom: 16px; line-height: 1.5; }
        .deliverables { list-style: none; margin-bottom: 20px; }
        .deliverables li { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 11px 14px; margin-bottom: 9px; font-size: 13.5px; color: #F8FAFC; line-height: 1.45; }

        .cta-dual { display: grid; grid-template-columns: 1.3fr 1fr; gap: 12px; }
        @media (max-width: 640px) { .cta-dual { grid-template-columns: 1fr; } }

        .btn-cta-main { display: flex; align-items: center; justify-content: center; text-align: center; background: #00C853; color: #fff; text-decoration: none; font-weight: 800; font-size: 15px; padding: 16px 18px; border-radius: 14px; box-shadow: 0 8px 22px rgba(0,200,83,0.35); transition: transform 0.15s, background 0.2s; }
        .btn-cta-main:hover { background: #00A645; transform: translateY(-1px); }
        .btn-cta-main.danger { background: #EF4444; box-shadow: 0 8px 22px rgba(239,68,68,0.35); }
        .btn-cta-main.danger:hover { background: #DC2626; }

        .btn-cta-agenda { display: flex; align-items: center; justify-content: center; text-align: center; background: rgba(255,255,255,0.12); color: #fff; border: 1.5px solid rgba(255,255,255,0.35); text-decoration: none; font-weight: 700; font-size: 14px; padding: 15px 16px; border-radius: 14px; transition: background 0.2s; }
        .btn-cta-agenda:hover { background: rgba(255,255,255,0.2); }

        .plano-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
        .plano-box { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px; }
        .plano-box small { display: block; font-size: 11.5px; color: #64748B; font-weight: 700; margin-bottom: 4px; }
        .plano-box strong { font-size: 18px; color: #0F172A; font-weight: 800; }

        .footer { text-align: center; font-size: 12px; color: #64748B; margin-top: 24px; line-height: 1.6; }
        @media print {
            body { background: #fff; padding: 0; }
            .btn-print, .offer-card { display: none !important; }
        }
    </style>
</head>
<body>
<div class="wrap">
    <div class="header-card">
        <div class="top-meta">
            <span class="tag-brand">📊 DOUTOR CAIXA • LAUDO EXECUTIVO</span>
            <button class="btn-print" onclick="window.print()">🖨️ Salvar PDF / Imprimir</button>
        </div>
        <h1>{{ lead.empresa }}</h1>
        <div class="header-sub">
            CNPJ: {{ lead.cnpj | cnpj_fmt }} {% if lead.cidade %}• {{ lead.cidade }}/{{ lead.uf }}{% endif %}<br>
            Solicitante: <strong>{{ lead.solicitante }}</strong> ({{ lead.cargo }}) • Segmento: {{ lead.ramo }}
        </div>
    </div>

    <!-- KPIs PRINCIPAIS -->
    <div class="kpi-grid">
        <div class="kpi-card">
            <small>Ponto de Equilíbrio</small>
            <div class="kpi-val">
                {% if diag.ponto_equilibrio %}{{ diag.ponto_equilibrio | moeda }}{% else %}Não calculável{% endif %}
            </div>
            <div class="kpi-note">
                {% if diag.ponto_equilibrio %}
                    Faturamento mínimo/mês para empatar as contas (margem {{ diag.margem_usada }}%{% if diag.margem_foi_estimada %} est.{% endif %}).
                {% else %}
                    Custos fixos não informados — impossível cravar o empate.
                {% endif %}
            </div>
        </div>

        <div class="kpi-card">
            <small>Resultado Operacional</small>
            <div class="kpi-val {% if diag.lucro_atual is not none %}{% if diag.lucro_atual < 0 %}red{% else %}green{% endif %}{% else %}amber{% endif %}">
                {% if diag.lucro_atual is not none %}{{ diag.lucro_atual | moeda }}/mês{% else %}Ponto Cego{% endif %}
            </div>
            <div class="kpi-note">
                {% if diag.lucro_atual is not none %}
                    {% if diag.lucro_atual < 0 %}Operação operando abaixo do ponto de equilíbrio.{% else %}Geração de caixa operacional estimada no mês.{% endif %}
                {% else %}
                    Faltam dados de faturamento ou custos fixos para medir o lucro real.
                {% endif %}
            </div>
        </div>

        <div class="kpi-card">
            <small>Dinheiro na Mesa (Mês)</small>
            <div class="kpi-val amber">+{{ diag.potencial_oculto | moeda }}</div>
            <div class="kpi-note">Ganho mensal estimado ao alinhar margem e conversão ao benchmark do setor.</div>
        </div>

        <div class="kpi-card">
            <small>Pontos Cegos Detectados</small>
            <div class="kpi-val {% if diag.qtd_cegas >= 2 %}red{% else %}green{% endif %}">{{ diag.qtd_cegas }} alerta(s)</div>
            <div class="kpi-note">Vulnerabilidades financeiras ou comerciais identificadas.</div>
        </div>
    </div>

    <!-- BENCHMARK SETORIAL USANDO CNAE -->
    <div class="bench-card">
        <div class="bench-title">📊 Benchmark Comparativo Setorial {% if lead.cnae %}— CNAE: {{ lead.cnae }}{% endif %}</div>
        <div class="bench-text">
            Empresas de alta performance no segmento <strong>{{ diag.bench.segmento }}</strong> operam com <strong>margem de contribuição acima de {{ diag.bench.margem_bench | int }}%</strong> e <strong>taxa de fechamento comercial de {{ diag.bench.conv_bench | int }}%</strong>.
            {{ diag.bench.alerta }}
        </div>
    </div>

    <!-- RADAR DE PONTOS CEGOS -->
    <div class="section-card">
        <div class="section-title">🚨 Radar de Pontos Cegos & Riscos de Caixa</div>
        {% if diag.pontos_cegos %}
            {% for item in diag.pontos_cegos %}
            <div class="cega-item {% if item.severidade == 'ALTO' %}alto{% elif item.severidade == 'MÉDIO' %}medio{% endif %}">
                <div class="cega-head">
                    <strong>{{ item.titulo }}</strong>
                    <span class="sev-badge">{{ item.severidade }}</span>
                </div>
                <div class="cega-desc">{{ item.descricao }}</div>
            </div>
            {% endfor %}
        {% else %}
            <p style="font-size:14px; color:#334155;">Sua operação apresentou indicadores saudáveis dentro dos parâmetros informados. O próximo passo é escalar previsibilidade comercial.</p>
        {% endif %}
    </div>

    <!-- BLOCO DE OFERTA: SESSÃO ESTRATÉGICA (20 MIN) COM ESCASSEZ REAL -->
    <div class="offer-card">
        <div class="scarcity-pill">⚠️ Limitado a 4 empresas por semana na Grande Recife ({{ vagas_restantes }} vagas restantes esta semana)</div>
        <h2>Sessão de Diagnóstico Comercial & Caixa (20 min — Gratuita)</h2>
        <p class="offer-sub">
            Não deixe esses números parados na tela. Vamos abrir o diagnóstico da <strong>{{ lead.empresa }}</strong> ao vivo com um especialista da MaqTrak para entregar 3 ações práticas:
        </p>
        <ul class="deliverables">
            <li><strong>1. Revisão da Margem & Ponto de Equilíbrio:</strong> ajuste fino de precificação e estancamento imediato de vazamentos de caixa.</li>
            <li><strong>2. Ajuste do Funil Diário da Equipe:</strong> definição exata de metas de contatos/dia, visitas semanais e script de follow-up.</li>
            <li><strong>3. Plano de Ação de 30 Dias:</strong> roteiro prático para capturar os <strong>{{ diag.potencial_oculto | moeda }}/mês</strong> deixados na mesa.</li>
        </ul>

        <div class="cta-dual">
            <a href="/cta-wpp/{{ lead.cnpj }}" target="_blank" class="btn-cta-main {% if diag.cta_cor == 'danger' %}danger{% endif %}">
                {{ diag.cta_texto }}
            </a>
            <a href="/cta-agenda/{{ lead.cnpj }}" target="_blank" class="btn-cta-agenda">
                📅 Escolher Horário na Agenda (15 min)
            </a>
        </div>
    </div>

    <!-- PLANO DE EXECUÇÃO COMERCIAL PARA BATER A META -->
    <div class="section-card">
        <div class="section-title">🎯 Engenharia de Metas para Bater {{ diag.meta_fat | moeda }}/mês</div>
        <div class="plano-grid">
            <div class="plano-box">
                <small>Vendas / Pedidos no Mês</small>
                <strong>{{ diag.vendas_necessarias_mes | num }} fechamentos</strong>
            </div>
            <div class="plano-box">
                <small>Oportunidades Qualificadas/Mês</small>
                <strong>{{ diag.oportunidades_mes | num }} orçamentos</strong>
            </div>
            <div class="plano-box">
                <small>Ritmo Diário por Vendedor</small>
                <strong>{{ diag.contatos_dia_por_vendedor }} contatos/dia</strong>
            </div>
            <div class="plano-box">
                <small>Cadência Semanal por Vendedor</small>
                <strong>{{ diag.visitas_semana_por_vendedor }} visitas/reuniões</strong>
            </div>
        </div>
    </div>

    <div class="footer">
        Diagnóstico gerado em {{ lead.atualizado_em }} • <strong>Doutor Caixa</strong> — Uma solução <strong>MaqTrak</strong>.<br>
        Dados tratados sob sigilo empresarial conforme a LGPD.
    </div>
</div>
</body>
</html>
"""


TEMPLATE_LOGIN_PAINEL = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Acesso Restrito — Painel Doutor Caixa</title>
    <style>
        * { box-sizing: border-box; font-family: system-ui, -apple-system, sans-serif; }
        body { background: #0F172A; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 16px; }
        .card { background: #fff; padding: 30px 26px; border-radius: 18px; width: 100%; max-width: 380px; }
        h2 { margin: 0 0 8px; color: #0F172A; font-size: 20px; }
        p { margin: 0 0 18px; color: #64748B; font-size: 13.5px; }
        input { width: 100%; padding: 12px 14px; border: 1.5px solid #CBD5E1; border-radius: 10px; font-size: 15px; margin-bottom: 14px; }
        button { width: 100%; padding: 13px; border: none; border-radius: 10px; background: #00C853; color: #fff; font-weight: 700; font-size: 15px; cursor: pointer; }
        .erro { color: #DC2626; font-size: 13px; font-weight: 600; margin-bottom: 12px; }
    </style>
</head>
<body>
    <form class="card" method="POST">
        <h2>🔒 Painel Doutor Caixa</h2>
        <p>Digite a senha de gestor para acessar o CRM de diagnósticos.</p>
        {% if erro %}<div class="erro">{{ erro }}</div>{% endif %}
        <input type="password" name="senha" placeholder="Senha de acesso" required autofocus>
        <button type="submit">Entrar no Painel →</button>
    </form>
</body>
</html>
"""


TEMPLATE_PAINEL = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CRM & Leads — Doutor Caixa</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: #F1F5F9; color: #0F172A; padding: 20px 14px 60px; }
        .wrap { max-width: 1120px; margin: 0 auto; }

        .topbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }
        .topbar h1 { font-size: 22px; font-weight: 800; }
        .topbar-actions { display: flex; gap: 10px; }
        .btn-top { padding: 9px 14px; border-radius: 10px; font-size: 13px; font-weight: 700; text-decoration: none; background: #fff; color: #0F172A; border: 1px solid #CBD5E1; }

        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
        .stat-card { background: #fff; border-radius: 14px; padding: 16px; border: 1px solid #E2E8F0; }
        .stat-card small { font-size: 11.5px; color: #64748B; font-weight: 700; text-transform: uppercase; }
        .stat-card strong { display: block; font-size: 24px; font-weight: 800; margin-top: 4px; }

        .filters { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; align-items: center; }
        .filter-btn { padding: 8px 13px; border-radius: 99px; border: 1px solid #CBD5E1; background: #fff; font-size: 12.5px; font-weight: 700; cursor: pointer; color: #334155; }
        .filter-btn.active { background: #0F172A; color: #fff; border-color: #0F172A; }
        .search-inp { margin-left: auto; padding: 8px 14px; border-radius: 10px; border: 1px solid #CBD5E1; font-size: 13px; min-width: 240px; }

        .lead-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
        .lead-card { background: #fff; border-radius: 16px; padding: 18px; border: 1px solid #E2E8F0; box-shadow: 0 2px 10px rgba(15,23,42,0.03); display: flex; flex-direction: column; justify-content: space-between; }
        .lead-card.incompleto { border-left: 5px solid #F59E0B; background: #FFFDF7; }
        .lead-card.quente { border-left: 5px solid #EF4444; }

        .badges { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
        .badge { font-size: 11px; font-weight: 800; padding: 3px 8px; border-radius: 6px; }
        .b-inc { background: #FEF3C7; color: #B45309; }
        .b-comp { background: #DCFCE7; color: #15803D; }
        .b-hot { background: #FEE2E2; color: #B91C1C; }

        .lead-title { font-size: 16px; font-weight: 800; color: #0F172A; margin-bottom: 3px; }
        .lead-meta { font-size: 12.5px; color: #64748B; margin-bottom: 12px; line-height: 1.45; }
        .lead-nums { background: #F8FAFC; border-radius: 10px; padding: 10px 12px; font-size: 12.5px; margin-bottom: 12px; line-height: 1.55; }

        .crm-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
        .crm-select { flex: 1; padding: 8px 10px; border-radius: 9px; border: 1.5px solid #CBD5E1; font-size: 12.5px; font-weight: 700; background: #fff; }
        .save-ok { font-size: 11.5px; font-weight: 700; color: #00A645; opacity: 0; transition: opacity 0.2s; }

        .card-actions { display: flex; gap: 8px; }
        .btn-act { flex: 1; text-align: center; padding: 9px 10px; border-radius: 9px; font-size: 12.5px; font-weight: 700; text-decoration: none; }
        .btn-wpp { background: #00C853; color: #fff; }
        .btn-laudo { background: #0F172A; color: #fff; }
        .btn-google { background: #EFF6FF; color: #1D4ED8; border: 1px solid #BFDBFE; }
    </style>
</head>
<body>
<div class="wrap">
    <div class="topbar">
        <h1>📊 Painel Comercial — Doutor Caixa</h1>
        <div class="topbar-actions">
            <a href="/" target="_blank" class="btn-top">+ Novo Diagnóstico</a>
            <a href="/painel/sair" class="btn-top">Sair</a>
        </div>
    </div>

    <div class="stats-grid">
        <div class="stat-card"><small>Total Capturados</small><strong>{{ stats.total }}</strong></div>
        <div class="stat-card"><small>Laudos Completos</small><strong style="color:#00A645;">{{ stats.completos }}</strong></div>
        <div class="stat-card"><small>Leads Incompletos</small><strong style="color:#D97706;">{{ stats.incompletos }}</strong></div>
        <div class="stat-card"><small>Cliques no CTA 🔥</small><strong style="color:#DC2626;">{{ stats.cliques_cta }}</strong></div>
        <div class="stat-card"><small>Reuniões Agendadas</small><strong style="color:#2563EB;">{{ stats.reunioes }}</strong></div>
    </div>

    <div class="filters">
        <button class="filter-btn active" onclick="filtrar('TODOS', this)">Todos ({{ stats.total }})</button>
        <button class="filter-btn" onclick="filtrar('Lead Incompleto', this)">⚠️ Incompletos ({{ stats.incompletos }})</button>
        <button class="filter-btn" onclick="filtrar('Novo', this)">Novos</button>
        <button class="filter-btn" onclick="filtrar('Contatado', this)">Contatados</button>
        <button class="filter-btn" onclick="filtrar('Reunião Agendada', this)">Reunião Agendada</button>
        <button class="filter-btn" onclick="filtrar('Proposta Enviada', this)">Proposta Enviada</button>
        <button class="filter-btn" onclick="filtrar('Fechado', this)">Fechados</button>
        <input type="text" class="search-inp" id="busca" placeholder="Buscar empresa, CNPJ ou cidade..." onkeyup="buscarTexto()">
    </div>

    <div class="lead-grid" id="lead-grid">
        {% for l in leads %}
        <div class="lead-card {% if not l.completo %}incompleto{% elif l.clicou_cta %}quente{% endif %}"
             data-status="{{ l.status_crm }}"
             data-search="{{ (l.empresa ~ ' ' ~ l.cnpj ~ ' ' ~ (l.cidade or '') ~ ' ' ~ (l.solicitante or '')) | lower }}">
            <div>
                <div class="badges">
                    {% if l.completo %}
                        <span class="badge b-comp">✅ Completo</span>
                    {% else %}
                        <span class="badge b-inc">⏳ Lead Incompleto (Abandonou Etapa 2+)</span>
                    {% endif %}
                    {% if l.clicou_cta %}
                        <span class="badge b-hot">🔥 Clicou no CTA ({{ l.data_cta or 'Hoje' }})</span>
                    {% endif %}
                </div>

                <div class="lead-title">{{ l.empresa }}</div>
                <div class="lead-meta">
                    CNPJ: {{ l.cnpj | cnpj_fmt }} {% if l.cidade %}• {{ l.cidade }}/{{ l.uf }}{% endif %}<br>
                    {% if l.cnae %}CNAE: {{ l.cnae[:65] }}...<br>{% endif %}
                    {% if l.solicitante %}
                        👤 <strong>{{ l.solicitante }}</strong> ({{ l.cargo }}) • 📱 {{ l.whatsapp }}
                    {% else %}
                        <em>Contato ainda não preenchido (abandono na etapa financeira)</em>
                    {% endif %}
                </div>

                {% if l.completo %}
                <div class="lead-nums">
                    💵 Fat: <strong>{{ l.faturamento | moeda }}</strong> | Margem: <strong>{% if l.margem %}{{ l.margem }}%{% else %}Não informou{% endif %}</strong><br>
                    🚨 Pontos Cegos: <strong>{{ l.qtd_cegas }}</strong> | Potencial: <strong style="color:#00A645;">{{ l.potencial_oculto | moeda }}/mês</strong>
                </div>
                {% endif %}
            </div>

            <div>
                <div class="crm-row">
                    <select class="crm-select" onchange="atualizarStatus('{{ l.cnpj }}', this)">
                        {% for st in ['Lead Incompleto', 'Novo', 'Contatado', 'Reunião Agendada', 'Proposta Enviada', 'Fechado', 'Perdido'] %}
                        <option value="{{ st }}" {% if l.status_crm == st %}selected{% endif %}>{{ st }}</option>
                        {% endfor %}
                    </select>
                    <span class="save-ok" id="ok-{{ l.cnpj }}">Salvo ✓</span>
                </div>

                <div class="card-actions">
                    {% if l.whatsapp %}
                        {% set wpp_num = l.whatsapp | replace('(', '') | replace(')', '') | replace('-', '') | replace(' ', '') %}
                        {% set msg_abordagem = "Olá " ~ l.solicitante ~ "! Tudo bem? Aqui é o Rodrigo da MaqTrak / Doutor Caixa. Vi o diagnóstico da " ~ l.empresa ~ " e identifiquei " ~ (l.qtd_cegas or 0) ~ " pontos importantes no caixa/comercial. Podemos falar 5 minutos?" %}
                        <a href="https://wa.me/55{{ wpp_num }}?text={{ msg_abordagem | urlencode }}" target="_blank" class="btn-act btn-wpp">💬 Chamar Lead</a>
                        <a href="/laudo/{{ l.cnpj }}" target="_blank" class="btn-act btn-laudo">📄 Ver Laudo</a>
                    {% else %}
                        <a href="https://www.google.com/search?q={{ (l.empresa ~ ' ' ~ (l.cidade or '') ~ ' telefone whatsapp') | urlencode }}" target="_blank" class="btn-act btn-google">🔍 Buscar Contato no Google</a>
                    {% endif %}
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>

<script>
    let filtroAtual = 'TODOS';

    function filtrar(status, btn) {
        filtroAtual = status;
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        aplicarFiltros();
    }

    function buscarTexto() {
        aplicarFiltros();
    }

    function aplicarFiltros() {
        const termo = document.getElementById('busca').value.toLowerCase().trim();
        document.querySelectorAll('.lead-card').forEach(card => {
            const st = card.getAttribute('data-status');
            const txt = card.getAttribute('data-search');
            const matchStatus = (filtroAtual === 'TODOS' || st === filtroAtual);
            const matchTexto = (!termo || txt.includes(termo));
            card.style.display = (matchStatus && matchTexto) ? 'flex' : 'none';
        });
    }

    async function atualizarStatus(cnpj, selectEl) {
        const novoStatus = selectEl.value;
        const card = selectEl.closest('.lead-card');
        card.setAttribute('data-status', novoStatus);

        try {
            const resp = await fetch('/api/lead-status', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cnpj: cnpj, status: novoStatus })
            });
            if (resp.ok) {
                const okEl = document.getElementById(`ok-${cnpj}`);
                okEl.style.opacity = '1';
                setTimeout(() => { okEl.style.opacity = '0'; }, 1800);
            }
        } catch (e) {}
    }
</script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)