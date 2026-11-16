import os
import json
import sqlite3
import threading
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template_string, request, redirect, url_for, make_response, jsonify
from fpdf import FPDF

app = Flask(__name__)

# ==============================================================================
# CONFIGURAÇÕES E VARIÁVEIS DE AMBIENTE (RENDER)
# ==============================================================================
DB_PATH = os.environ.get("DB_PATH", "doutor_caixa.db")
WHATSAPP_CONSULTOR = os.environ.get("WHATSAPP_CONSULTOR", "5581979091165").strip()
PAINEL_SENHA = os.environ.get("PAINEL_SENHA", "maqtrak2026").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "9209744162:AAE-Yg8v1EBtifwf1LnF6gQSLf8kDbtkhuQ").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "7635246193").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

FUSO_BR = timezone(timedelta(hours=-3))


def agora_br():
    return datetime.now(FUSO_BR).strftime("%d/%m/%Y %H:%M")


# ==============================================================================
# CATÁLOGO DE PONTOS CEGOS SELECIONÁVEIS (ETAPAS 2 E 3)
# ==============================================================================
GARGALOS_CATALOGO = {
    "sem_margem_real": {
        "etapa": "financeiro",
        "label": "Não sei a margem de lucro real de cada produto/serviço",
        "titulo": "Precificação sem Margem de Contribuição Real",
        "severidade": "CRÍTICO",
        "descricao": "Vender sem conhecer a margem líquida unitária faz a empresa crescer faturamento enquanto corrói o caixa a cada venda."
    },
    "mistura_contas": {
        "etapa": "financeiro",
        "label": "Misturo contas pessoais dos sócios com o caixa da empresa",
        "titulo": "Confusão Patrimonial (Caixa Empresa x Sócios)",
        "severidade": "CRÍTICO",
        "descricao": "Retiradas sem pró-labore definido descapitalizam o giro operacional e mascaram a real lucratividade do negócio."
    },
    "desconto_sem_calculo": {
        "etapa": "financeiro",
        "label": "Dou descontos para fechar venda sem calcular o impacto no lucro",
        "titulo": "Concessão de Descontos Sem Critério de Margem",
        "severidade": "ALTO",
        "descricao": "Um desconto de 10% no preço exige até 30% a mais de volume de vendas apenas para empatar o mesmo lucro bruto."
    },
    "fatura_sem_sobrar": {
        "etapa": "financeiro",
        "label": "A empresa fatura bem, mas no fim do mês não sobra dinheiro",
        "titulo": "Descompasso Entre Faturamento e Geração de Caixa",
        "severidade": "CRÍTICO",
        "descricao": "Sinal clássico de custos fixos inchados, prazos de recebimento descasados ou margem comprimida na operação."
    },
    "sem_fluxo_diario": {
        "etapa": "financeiro",
        "label": "Falta controle diário de fluxo de caixa e ponto de equilíbrio",
        "titulo": "Gestão Financeira Reativa (Sem Previsão de Caixa)",
        "severidade": "ALTO",
        "descricao": "Operar olhando apenas o saldo bancário do dia impede antecipar apertos de caixa e planejar investimentos."
    },
    "sem_meta_diaria": {
        "etapa": "comercial",
        "label": "Equipe comercial sem metas diárias de contatos e visitas",
        "titulo": "Baixa Cadência de Prospecção Comercial",
        "severidade": "ALTO",
        "descricao": "Sem rotina mínima diária de abordagens ativas e visitas, o funil seca e o faturamento oscila mês a mês."
    },
    "sem_followup": {
        "etapa": "comercial",
        "label": "Orçamentos enviados sem follow-up estruturado (leads esfriam)",
        "titulo": "Vazamento no Funil por Falta de Follow-up",
        "severidade": "CRÍTICO",
        "descricao": "Mais de 60% das vendas B2B e consultivas acontecem após o 4º contato. Sem cadência, você paga pelo lead e entrega ao concorrente."
    },
    "dependencia_dono": {
        "etapa": "comercial",
        "label": "Dependência total do dono para fechar as principais vendas",
        "titulo": "Gargalo de Escala Centralizado no Sócio",
        "severidade": "ALTO",
        "descricao": "Quando só o dono sabe vender, a empresa bate num teto de faturamento e o gestor fica preso no operacional."
    },
    "sem_crm_processo": {
        "etapa": "comercial",
        "label": "Falta de CRM ou processo previsível para gerar oportunidades",
        "titulo": "Funil Comercial Sem Rastreabilidade (Sem CRM)",
        "severidade": "MÉDIO",
        "descricao": "Sem registro de etapas e motivos de perda, é impossível corrigir onde os vendedores estão perdendo negócios."
    },
    "conversao_baixa": {
        "etapa": "comercial",
        "label": "Muitos orçamentos/atendimentos, mas poucos fechamentos",
        "titulo": "Baixa Eficiência de Conversão no Atendimento",
        "severidade": "ALTO",
        "descricao": "Falha na qualificação inicial ou na ancoragem de valor faz a equipe gastar energia com curiosos e perder clientes prontos."
    }
}


# ==============================================================================
# BANCO DE DADOS (SQLITE + MIGRAÇÃO AUTOMÁTICA)
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
            gargalos_json TEXT,
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
    try:
        cur.execute("ALTER TABLE leads ADD COLUMN gargalos_json TEXT")
    except Exception:
        pass
    conn.commit()
    conn.close()


init_db()


def sync_supabase_async(payload: dict):
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
# FORMATAÇÃO, LINKS WHATSAPP COM ESPAÇAMENTO E INTELIGÊNCIA SETORIAL
# ==============================================================================
def limpar_cnpj(cnpj: str) -> str:
    return "".join(filter(str.isdigit, str(cnpj or "")))[:14]


def formatar_cnpj(cnpj: str) -> str:
    d = limpar_cnpj(cnpj)
    if len(d) != 14:
        return cnpj or ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def normalizar_telefone_br(telefone: str) -> str:
    digitos = "".join(filter(str.isdigit, str(telefone or "")))
    if not digitos:
        return ""
    if digitos.startswith("55") and len(digitos) in (12, 13):
        return digitos
    if len(digitos) in (10, 11):
        return f"55{digitos}"
    return digitos


def gerar_link_abordagem_cliente(lead: dict, diag: dict, tipo: str = "novo") -> str:
    tel_cliente = normalizar_telefone_br(lead.get("whatsapp", ""))
    if not tel_cliente:
        return ""

    solicitante = (lead.get("solicitante") or "").strip()
    primeiro_nome = solicitante.split()[0] if solicitante else "tudo bem"
    empresa = (lead.get("empresa") or "sua empresa").strip()
    qtd_cegas = diag.get("qtd_cegas", 0)
    potencial_txt = fmt_moeda(diag.get("potencial_oculto"))
    lucro_atual = diag.get("lucro_atual")

    if lucro_atual is not None and lucro_atual < 0:
        diagnostico_frase = (
            f"No laudo da *{empresa}*, identificamos um alerta crítico de déficit estimado em *{fmt_moeda(abs(lucro_atual))}/mês* "
            f"e *{potencial_txt}/mês* em potencial oculto."
        )
    else:
        diagnostico_frase = (
            f"No laudo da *{empresa}*, identificamos *{qtd_cegas} ponto(s) cego(s)* de gestão "
            f"e um potencial oculto de *{potencial_txt}/mês* sendo deixado na mesa."
        )

    if tipo == "agenda":
        frases = [
            f"Olá, {primeiro_nome}! Tudo bem?",
            "Aqui é da equipe *Doutor Caixa / MaqTrak*.",
            "Recebi sua solicitação para agendar a Sessão Estratégica gratuita da sua empresa.",
            diagnostico_frase,
            "Qual o melhor horário para falarmos hoje ou amanhã?"
        ]
    elif tipo == "urgente":
        frases = [
            f"Olá, {primeiro_nome}! Tudo bem?",
            "Aqui é da equipe *Doutor Caixa / MaqTrak*.",
            "Acabei de receber seu chamado prioritário pelo diagnóstico que você gerou.",
            diagnostico_frase,
            "Vamos fazer uma conversa rápida de 15 minutos para te mostrar o plano prático para estancar esses vazamentos?"
        ]
    else:
        frases = [
            f"Olá, {primeiro_nome}! Tudo bem?",
            "Aqui é da equipe *Doutor Caixa / MaqTrak*.",
            "Vi que você acabou de emitir o diagnóstico executivo da sua empresa.",
            diagnostico_frase,
            "Posso te mostrar em 15 minutos como capturar esse resultado nos próximos 30 dias?"
        ]

    msg = "\n\n".join(frases)
    return f"https://wa.me/{tel_cliente}?text={urllib.parse.quote(msg)}"


def parse_float_opcional(valor):
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


def pdf_safe(texto) -> str:
    s = (
        str(texto or "")
        .replace("—", "-")
        .replace("–", "-")
        .replace("•", "-")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
    )
    return s.encode("latin-1", "ignore").decode("latin-1")


app.jinja_env.filters["moeda"] = fmt_moeda
app.jinja_env.filters["num"] = fmt_num
app.jinja_env.filters["cnpj_fmt"] = formatar_cnpj
app.jinja_env.filters["tel_br"] = normalizar_telefone_br


def obter_benchmark_setorial(cnae: str, ramo: str) -> dict:
    texto = f"{cnae or ''} {ramo or ''}".lower()

    if any(k in texto for k in ["saúde", "clínica", "médic", "odont", "estética", "hospital", "laborat"]):
        return {
            "segmento": "Saúde, Clínicas & Estética",
            "margem_bench": 52.0,
            "conv_bench": 28.0,
            "alerta": "Clínicas de alta performance protegem margem acima de 52% e convertem quase 1 a cada 3 avaliações agendadas."
        }
    if any(k in texto for k in ["software", "saas", "tecnologia", "ti", "informática", "agência", "marketing", "consultoria", "serviço", "b2b"]):
        return {
            "segmento": "Serviços B2B, Agências & Tecnologia",
            "margem_bench": 58.0,
            "conv_bench": 22.0,
            "alerta": "Operações B2B líderes operam com margem de contribuição acima de 58% e taxa de fechamento de 22% sobre propostas enviadas."
        }
    if any(k in texto for k in ["indústria", "fabric", "metal", "máquina", "equipamento", "engenharia", "construção"]):
        return {
            "segmento": "Indústria, Máquinas & Bens de Capital",
            "margem_bench": 34.0,
            "conv_bench": 18.0,
            "alerta": "Empresas industriais e de bens de capital referência mantêm margem acima de 34% e conversão de 18% no pipeline técnico."
        }
    if any(k in texto for k in ["recorrência", "assinatura", "educação", "escola", "academia", "telecom", "segurança"]):
        return {
            "segmento": "Receita Recorrente & Assinaturas",
            "margem_bench": 62.0,
            "conv_bench": 25.0,
            "alerta": "Negócios recorrentes saudáveis operam com margem acima de 62% e retenção superior a 95% ao mês."
        }
    return {
        "segmento": "Comércio, Varejo & Distribuição",
        "margem_bench": 32.0,
        "conv_bench": 24.0,
        "alerta": "Distribuidoras e varejistas de alta performance operam com margem de contribuição acima de 32% e conversão de 24% no atendimento."
    }


def processar_diagnostico(dados: dict) -> dict:
    fat = dados.get("faturamento")
    margem = dados.get("margem")
    fixos = dados.get("custos_fixos")
    ticket = dados.get("ticket_medio")
    leads_mes = dados.get("leads_mes")
    taxa_conv = dados.get("taxa_conv")
    vendedores = dados.get("vendedores")
    meta_fat = dados.get("meta_fat")
    gargalos_selecionados = dados.get("gargalos") or []

    bench = obter_benchmark_setorial(dados.get("cnae", ""), dados.get("ramo", ""))
    pontos_cegos = []
    titulos_vistos = set()

    def adicionar_ponto_cego(titulo: str, severidade: str, descricao: str, topo: bool = False):
        if titulo in titulos_vistos:
            return
        titulos_vistos.add(titulo)
        item = {"titulo": titulo, "severidade": severidade, "descricao": descricao}
        if topo:
            pontos_cegos.insert(0, item)
        else:
            pontos_cegos.append(item)

    for cod in gargalos_selecionados:
        info = GARGALOS_CATALOGO.get(cod)
        if info:
            adicionar_ponto_cego(info["titulo"], info["severidade"], info["descricao"])

    if fat is None:
        adicionar_ponto_cego(
            "Faturamento Mensal Não Informado",
            "CRÍTICO",
            "Sem visibilidade exata da receita mensal, qualquer meta de crescimento ou corte de custos vira chute."
        )
    if margem is None:
        adicionar_ponto_cego(
            "Margem de Contribuição Desconhecida (Gestão no Escuro)",
            "CRÍTICO",
            f"Você não soube informar sua margem. Usamos {bench['margem_bench']:.0f}% (média do setor) como referência, mas vender sem saber a margem real é a causa nº 1 de empresas que faturam alto e quebram sem caixa."
        )
    if fixos is None:
        adicionar_ponto_cego(
            "Custos Fixos Mensais Não Mapeados",
            "ALTO",
            "Sem conhecer o custo fixo total da estrutura, você não sabe em qual dia do mês a empresa começa a dar lucro."
        )
    if leads_mes is None or taxa_conv is None:
        adicionar_ponto_cego(
            "Funil Comercial Sem Previsibilidade (Leads / Conversão)",
            "ALTO",
            "Faltam métricas de entrada de oportunidades ou taxa de fechamento. Sem medir o funil, o faturamento fica refém da sorte."
        )
    if ticket is None:
        adicionar_ponto_cego(
            "Ticket Médio Não Monitorado",
            "MÉDIO",
            "Sem acompanhar o ticket médio, a equipe comercial tende a dar descontos excessivos para fechar pedidos."
        )

    margem_calc = margem if (margem is not None and margem > 0) else bench["margem_bench"]
    margem_dec = margem_calc / 100.0

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

    if lucro_atual is not None and lucro_atual < 0:
        adicionar_ponto_cego(
            f"Hemorragia de Caixa: Déficit Estimado de {fmt_moeda(abs(lucro_atual))}/mês",
            "CRÍTICO",
            f"Com a margem atual de {margem_calc:.1f}%, o faturamento não cobre os custos fixos de {fmt_moeda(fixos)}. A operação está queimando caixa todos os meses.",
            topo=True
        )

    if margem is not None and margem < bench["margem_bench"]:
        dif_m = bench["margem_bench"] - margem
        adicionar_ponto_cego(
            f"Margem de Contribuição {dif_m:.1f} p.p. Abaixo do Setor",
            "ALTO",
            f"Sua margem informada ({margem:.1f}%) está abaixo da referência de alta performance do segmento ({bench['margem_bench']:.0f}%), comprimindo a sobra de caixa."
        )

    if taxa_conv is not None and taxa_conv < bench["conv_bench"]:
        dif_c = bench["conv_bench"] - taxa_conv
        adicionar_ponto_cego(
            f"Taxa de Fechamento {dif_c:.1f} p.p. Abaixo da Média do Mercado",
            "ALTO",
            f"Sua conversão ({taxa_conv:.1f}%) está abaixo do benchmark ({bench['conv_bench']:.0f}%). Melhorar abordagem e follow-up destrava faturamento imediato sem gastar mais com anúncios."
        )

    potencial_oculto = 0.0
    if fat is not None and fat > 0 and margem is not None and margem < bench["margem_bench"]:
        potencial_oculto += fat * ((bench["margem_bench"] - margem) / 100.0)

    if leads_mes is not None and leads_mes > 0 and taxa_conv is not None and taxa_conv < bench["conv_bench"]:
        tk_ref = ticket if (ticket is not None and ticket > 0) else 1500.0
        vendas_extras = leads_mes * ((bench["conv_bench"] - taxa_conv) / 100.0)
        potencial_oculto += vendas_extras * tk_ref

    if potencial_oculto <= 0:
        fator_extra = 0.18 + (0.02 * min(len(gargalos_selecionados), 5))
        potencial_oculto = (fat * fator_extra) if (fat is not None and fat > 0) else 15000.0

    if meta_fat is None or meta_fat <= 0:
        if ponto_equilibrio and fat:
            meta_fat = max(fat * 1.25, ponto_equilibrio * 1.20)
        elif fat:
            meta_fat = fat * 1.25
        else:
            meta_fat = 100000.0

    eq_vendedores = int(vendedores) if (vendedores is not None and vendedores >= 1) else 1
    tk_calc = ticket if (ticket is not None and ticket > 0) else 2500.0
    conv_calc = (taxa_conv / 100.0) if (taxa_conv is not None and taxa_conv > 0) else (bench["conv_bench"] / 100.0)

    vendas_necessarias_mes = meta_fat / tk_calc
    oportunidades_mes = vendas_necessarias_mes / max(conv_calc, 0.05)
    contatos_dia_por_vendedor = max(30, int(round((oportunidades_mes * 3) / (22 * eq_vendedores))))
    visitas_semana_por_vendedor = max(20, int(round((oportunidades_mes / 4.3) / eq_vendedores)))

    qtd_cegas = len(pontos_cegos)
    empresa_nome = dados.get("empresa") or "minha empresa"
    tem_critico = any(p.get("severidade") == "CRÍTICO" for p in pontos_cegos)
    pot_fmt = fmt_moeda(potencial_oculto)

    # CTA DINÂMICO DE ALTA URGÊNCIA BASEADO NO DIAGNÓSTICO DO LAUDO
    if lucro_atual is not None and lucro_atual < 0:
        cta_texto = f"🚨 Estancar Prejuízo de {fmt_moeda(abs(lucro_atual))}/mês Agora"
        cta_cor = "danger"
    elif qtd_cegas >= 4 or (tem_critico and qtd_cegas >= 2):
        cta_texto = f"⚠️ Parar de Perder {pot_fmt}/mês ({qtd_cegas} Alertas)"
        cta_cor = "danger"
    elif qtd_cegas >= 1:
        cta_texto = f"🔥 Recuperar {pot_fmt}/mês na Mesa Agora"
        cta_cor = "warning"
    else:
        cta_texto = f"🚀 Capturar +{pot_fmt}/mês e Bater Meta Agora"
        cta_cor = "success"

    wpp_msg_principal = (
        f"Olá! Fiz o diagnóstico da *{empresa_nome}* no Doutor Caixa.\n\n"
        f"O laudo apontou *{qtd_cegas} ponto(s) cego(s)* e um potencial de *{pot_fmt}/mês* sendo deixado na mesa.\n\n"
        f"Quero estancar esses gargalos e conversar com um especialista agora."
    )

    wpp_msg_agenda = (
        f"Olá! Sou {dados.get('solicitante', 'Gestor')} da *{empresa_nome}*.\n\n"
        f"Recebi meu laudo no Doutor Caixa ({pot_fmt}/mês em potencial) e gostaria de agendar minha Sessão Estratégica gratuita."
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
        "wpp_msg": wpp_msg_principal,
        "wpp_msg_agenda": wpp_msg_agenda
    }


# ==============================================================================
# ROTAS DE API (CONSULTA CNPJ COM FALLBACK MÚLTIPLO)
# ==============================================================================
@app.route("/api/cnpj/<cnpj>")
def api_consultar_cnpj(cnpj):
    cnpj_limpo = limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        return jsonify({"ok": False, "erro": "CNPJ inválido"}), 400

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DoutorCaixa/8.0",
        "Accept": "application/json"
    }

    for url_api in [
        f"https://minhareceita.org/{cnpj_limpo}",
        f"https://publica.cnpj.ws/cnpj/{cnpj_limpo}",
        f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}"
    ]:
        try:
            req = urllib.request.Request(url_api, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if "minhareceita" in url_api:
                    nome = (data.get("nome_fantasia") or "").strip() or (data.get("razao_social") or "").strip()
                    cidade = (data.get("municipio") or "").strip()
                    uf = (data.get("uf") or "").strip()
                    cnae = (data.get("cnae_fiscal_descricao") or "").strip()
                elif "cnpj.ws" in url_api:
                    est = data.get("estabelecimento") or {}
                    nome = (est.get("nome_fantasia") or "").strip() or (data.get("razao_social") or "").strip()
                    cidade = (est.get("cidade") or {}).get("nome", "").strip()
                    uf = (est.get("estado") or {}).get("sigla", "").strip()
                    cnae = (est.get("atividade_principal") or {}).get("descricao", "").strip()
                else:
                    nome = (data.get("nome_fantasia") or "").strip() or (data.get("razao_social") or "").strip()
                    cidade = (data.get("municipio") or "").strip()
                    uf = (data.get("uf") or "").strip()
                    cnae = (data.get("cnae_fiscal_descricao") or "").strip()

                if nome:
                    return jsonify({"ok": True, "nome": nome, "municipio": cidade, "uf": uf, "cnae": cnae})
        except Exception:
            continue

    return jsonify({"ok": False, "erro": "Não encontrado nas bases públicas"}), 404


@app.route("/api/lead-parcial", methods=["POST"])
def api_lead_parcial():
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
    return jsonify({"ok": True})


@app.route("/api/lead-status", methods=["POST"])
def api_lead_status():
    if request.cookies.get("painel_auth") != PAINEL_SENHA:
        return jsonify({"ok": False, "erro": "Não autorizado"}), 401

    body = request.get_json(silent=True) or {}
    cnpj = limpar_cnpj(body.get("cnpj", ""))
    novo_status = (body.get("status") or "").strip()
    status_validos = ["Lead Incompleto", "Novo", "Contatado", "Reunião Agendada", "Proposta Enviada", "Fechado", "Perdido"]
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
# ROTAS DE RASTREAMENTO DE CONVERSÃO (WHATSAPP + TELEGRAM)
# ==============================================================================
@app.route("/cta-wpp/<cnpj>")
def cta_whatsapp(cnpj):
    cnpj_limpo = limpar_cnpj(cnpj)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM leads WHERE cnpj = ?", (cnpj_limpo,))
    lead = cur.fetchone()

    ts = agora_br()
    wpp_msg_para_consultor = "Olá! Fiz meu diagnóstico no Doutor Caixa e quero estancar meus prejuízos."

    if lead:
        lead_dict = dict(lead)
        cur.execute("UPDATE leads SET clicou_cta = 1, data_cta = ?, atualizado_em = ? WHERE cnpj = ?", (ts, ts, cnpj_limpo))
        conn.commit()

        diag = json.loads(lead_dict.get("diagnostico_json") or "{}")
        if diag.get("wpp_msg"):
            wpp_msg_para_consultor = diag["wpp_msg"]

        link_abordar_cliente = gerar_link_abordagem_cliente(lead_dict, diag, tipo="urgente")

        alerta = (
            f"🔥 <b>ALERTA QUENTE — BOTÃO PRINCIPAL (ESTANCAR PREJUÍZO)!</b>\n\n"
            f"🏢 <b>Empresa:</b> {lead_dict['empresa']} ({formatar_cnpj(cnpj_limpo)})\n"
            f"📍 <b>Local:</b> {lead_dict.get('cidade') or '-'}/{lead_dict.get('uf') or '-'}\n"
            f"👤 <b>Contato:</b> {lead_dict.get('solicitante') or '-'} ({lead_dict.get('cargo') or '-'})\n"
            f"📱 <b>WhatsApp do Cliente:</b> {lead_dict.get('whatsapp') or '-'}\n"
            f"🚨 <b>Pontos Cegos:</b> {lead_dict.get('qtd_cegas') or 0}\n"
            f"💰 <b>Potencial Oculto:</b> {fmt_moeda(lead_dict.get('potencial_oculto'))}\n\n"
            f"💬 <a href=\"{link_abordar_cliente}\"><b>ABORDAR CLIENTE NO WHATSAPP (MENSAGEM PERSONALIZADA)</b></a>"
        )
        enviar_telegram_async(alerta)

    conn.close()
    wpp_destino = normalizar_telefone_br(WHATSAPP_CONSULTOR)
    return redirect(f"https://wa.me/{wpp_destino}?text={urllib.parse.quote(wpp_msg_para_consultor)}", code=302)


@app.route("/cta-agenda/<cnpj>")
def cta_agenda(cnpj):
    cnpj_limpo = limpar_cnpj(cnpj)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM leads WHERE cnpj = ?", (cnpj_limpo,))
    lead = cur.fetchone()

    ts = agora_br()
    wpp_msg_para_consultor = "Olá! Gostaria de agendar minha Sessão Estratégica de 20 min no Doutor Caixa."

    if lead:
        lead_dict = dict(lead)
        cur.execute("UPDATE leads SET clicou_cta = 1, data_cta = ?, atualizado_em = ? WHERE cnpj = ?", (ts, ts, cnpj_limpo))
        conn.commit()

        diag = json.loads(lead_dict.get("diagnostico_json") or "{}")
        if diag.get("wpp_msg_agenda"):
            wpp_msg_para_consultor = diag["wpp_msg_agenda"]
        elif lead_dict.get("empresa"):
            wpp_msg_para_consultor = f"Olá! Sou {lead_dict.get('solicitante')} da *{lead_dict['empresa']}*.\n\nQuero agendar nossa Sessão Estratégica de 20 min."

        link_abordar_cliente = gerar_link_abordagem_cliente(lead_dict, diag, tipo="agenda")

        alerta = (
            f"📅 <b>ALERTA — QUER AGENDAR REUNIÃO (BOTÃO SECUNDÁRIO)!</b>\n\n"
            f"🏢 <b>Empresa:</b> {lead_dict['empresa']} ({formatar_cnpj(cnpj_limpo)})\n"
            f"👤 <b>Contato:</b> {lead_dict.get('solicitante') or '-'} ({lead_dict.get('cargo') or '-'})\n"
            f"📱 <b>WhatsApp do Cliente:</b> {lead_dict.get('whatsapp') or '-'}\n"
            f"💰 <b>Potencial Oculto:</b> {fmt_moeda(lead_dict.get('potencial_oculto'))}\n\n"
            f"💬 <a href=\"{link_abordar_cliente}\"><b>COMBINAR HORÁRIO NO WHATSAPP DO CLIENTE</b></a>"
        )
        enviar_telegram_async(alerta)

    conn.close()
    wpp_destino = normalizar_telefone_br(WHATSAPP_CONSULTOR)
    return redirect(f"https://wa.me/{wpp_destino}?text={urllib.parse.quote(wpp_msg_para_consultor)}", code=302)


# ==============================================================================
# ROTA PRINCIPAL E GERADOR DE PDF EXECUTIVO COMPLETO
# ==============================================================================
@app.route("/", methods=["GET"])
def index():
    origem = request.args.get("utm_source") or request.args.get("src") or "Direto"
    gargalos_fin = [(k, v["label"]) for k, v in GARGALOS_CATALOGO.items() if v["etapa"] == "financeiro"]
    gargalos_com = [(k, v["label"]) for k, v in GARGALOS_CATALOGO.items() if v["etapa"] == "comercial"]
    return render_template_string(
        TEMPLATE_DIAGNOSTICO,
        origem=origem,
        gargalos_fin=gargalos_fin,
        gargalos_com=gargalos_com
    )


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
    gargalos = request.form.getlist("gargalos")

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
        "gargalos": gargalos,
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
                qtd_cegas = ?, gargalos_json = ?, pontos_cegos_json = ?, diagnostico_json = ?,
                status_crm = ?, completo = 1, origem = ?, atualizado_em = ?
            WHERE cnpj = ?
        """, (
            empresa, cidade, uf, cnae, ramo,
            solicitante, cargo, whatsapp,
            dados["faturamento"], dados["margem"], dados["custos_fixos"], dados["ticket_medio"],
            dados["leads_mes"], dados["taxa_conv"], dados["vendedores"], diag["meta_fat"],
            diag["ponto_equilibrio"], diag["lucro_atual"], diag["potencial_oculto"],
            diag["qtd_cegas"], json.dumps(gargalos, ensure_ascii=False),
            json.dumps(diag["pontos_cegos"], ensure_ascii=False),
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
                qtd_cegas, gargalos_json, pontos_cegos_json, diagnostico_json,
                status_crm, completo, origem, criado_em, atualizado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (
            cnpj, empresa, cidade, uf, cnae, ramo,
            solicitante, cargo, whatsapp,
            dados["faturamento"], dados["margem"], dados["custos_fixos"], dados["ticket_medio"],
            dados["leads_mes"], dados["taxa_conv"], dados["vendedores"], diag["meta_fat"],
            diag["ponto_equilibrio"], diag["lucro_atual"], diag["potencial_oculto"],
            diag["qtd_cegas"], json.dumps(gargalos, ensure_ascii=False),
            json.dumps(diag["pontos_cegos"], ensure_ascii=False),
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

    link_abordar_cliente = gerar_link_abordagem_cliente(dados, diag, tipo="novo")
    alerta_novo = (
        f"✅ <b>NOVO DIAGNÓSTICO CONCLUÍDO!</b>\n\n"
        f"🏢 <b>Empresa:</b> {empresa} ({formatar_cnpj(cnpj)})\n"
        f"📍 <b>Cidade/UF:</b> {cidade or '-'}/{uf or '-'}\n"
        f"👤 <b>Solicitante:</b> {solicitante} ({cargo})\n"
        f"📱 <b>WhatsApp do Cliente:</b> {whatsapp}\n"
        f"💵 <b>Faturamento:</b> {fmt_moeda(dados['faturamento'])}\n"
        f"🚨 <b>Pontos Cegos:</b> {diag['qtd_cegas']}\n"
        f"💰 <b>Potencial Oculto:</b> {fmt_moeda(diag['potencial_oculto'])}/mês\n\n"
        f"💬 <a href=\"{link_abordar_cliente}\"><b>ABORDAR CLIENTE NO WHATSAPP (MENSAGEM PERSONALIZADA)</b></a>"
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
    dados["gargalos"] = json.loads(dados.get("gargalos_json") or "[]")
    diag = json.loads(dados.get("diagnostico_json") or "{}")
    if not diag:
        diag = processar_diagnostico(dados)

    return render_template_string(
        TEMPLATE_LAUDO,
        lead=dados,
        diag=diag,
        vagas_restantes=2
    )


@app.route("/baixar_pdf/<cnpj>")
def baixar_pdf(cnpj):
    cnpj_limpo = limpar_cnpj(cnpj)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM leads WHERE cnpj = ?", (cnpj_limpo,))
    lead = cur.fetchone()
    conn.close()

    if not lead:
        return "Lead não encontrado", 404

    dados = dict(lead)
    dados["gargalos"] = json.loads(dados.get("gargalos_json") or "[]")
    diag = json.loads(dados.get("diagnostico_json") or "{}")
    if not diag:
        diag = processar_diagnostico(dados)

    bench = diag.get("bench") or obter_benchmark_setorial(dados.get("cnae", ""), dados.get("ramo", ""))
    logo_path = os.path.join(app.root_path, "static", "logo.png")
    qr_path = os.path.join(app.root_path, "static", "qrcode_whatsapp.png")

    class PDF(FPDF):
        def header(self):
            if os.path.exists(logo_path):
                try:
                    self.image(logo_path, 12, 8, 28)
                except Exception:
                    pass
            self.set_text_color(15, 46, 28)
            self.set_font("Helvetica", "B", 14.5)
            self.set_xy(44, 12)
            self.cell(154, 6.5, pdf_safe("LAUDO EXECUTIVO DE CAIXA E VENDAS"), border=0, align="R")
            self.set_font("Helvetica", "", 8.5)
            self.set_text_color(100, 110, 105)
            self.set_xy(44, 19.5)
            self.cell(154, 4.5, pdf_safe("DOUTOR CAIXA - INTELIGENCIA COMERCIAL E FINANCEIRA"), border=0, align="R")
            self.set_xy(44, 24.5)
            self.cell(154, 4, pdf_safe(f"Emitido em: {dados.get('atualizado_em') or agora_br()}"), border=0, align="R")
            self.set_draw_color(213, 232, 220)
            self.set_line_width(0.4)
            self.line(12, 33, 198, 33)
            self.set_y(37)

        def footer(self):
            self.set_y(-14)
            self.set_font("Helvetica", "", 7.5)
            self.set_text_color(120, 130, 124)
            self.cell(0, 3.8, pdf_safe(f"Doutor Caixa | Inteligencia Financeira & Comercial - Pagina {self.page_no()}"), ln=1, align="C")
            self.cell(0, 3.8, pdf_safe("Doutor Caixa e uma empresa da MaqTrak - Hub de Solucoes em Inteligencia de Mercado."), align="C")

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=17)
    pdf.add_page()

    # 1. IDENTIFICAÇÃO DA EMPRESA & PARÂMETROS INFORMADOS
    y0 = pdf.get_y()
    box1_h = 27 if dados.get("cnae") else 22
    pdf.set_fill_color(247, 250, 248)
    pdf.rect(12, y0, 186, box1_h, "F")
    pdf.set_fill_color(0, 200, 83)
    pdf.rect(12, y0, 2.5, box1_h, "F")

    pdf.set_xy(18, y0 + 2.5)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(15, 23, 42)
    loc_pdf = f" ({dados['cidade']}/{dados['uf']})" if dados.get("cidade") and dados.get("uf") else ""
    pdf.cell(176, 5, pdf_safe(f"EMPRESA: {dados['empresa']}{loc_pdf} | CNPJ: {formatar_cnpj(cnpj_limpo)}"), ln=1)

    pdf.set_x(18)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(45, 55, 65)
    pdf.cell(176, 4.5, pdf_safe(f"Solicitante: {dados['solicitante']} ({dados['cargo']}) | WhatsApp: {dados.get('whatsapp') or '-'}"), ln=1)

    if dados.get("cnae"):
        pdf.set_x(18)
        pdf.cell(176, 4.5, pdf_safe(f"CNAE Oficial: {dados['cnae'][:88]}"), ln=1)

    pdf.set_x(18)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(0, 150, 62)
    margem_lbl = f"{diag.get('margem_usada', 0)}%" + (" (estimada)" if diag.get("margem_foi_estimada") else "")
    pdf.cell(
        176, 4.5,
        pdf_safe(f"Fat. Mensal: {fmt_moeda(dados.get('faturamento'))} | Margem: {margem_lbl} | Custos Fixos: {fmt_moeda(dados.get('custos_fixos'))}"),
        ln=1
    )
    pdf.set_y(y0 + box1_h + 4)

    # 2. OS 4 KPIs PRINCIPAIS
    y_kpi = pdf.get_y()
    card_w = 44.25
    gap_w = 3.0
    card_h = 24

    pe_txt = fmt_moeda(diag.get("ponto_equilibrio")) if diag.get("ponto_equilibrio") else "Nao calculavel"
    lucro_val = diag.get("lucro_atual")
    lucro_txt = f"{fmt_moeda(lucro_val)}/mes" if lucro_val is not None else "Ponto Cego"
    pot_txt = f"+{fmt_moeda(diag.get('potencial_oculto'))}"
    qtd_c = diag.get("qtd_cegas", 0)

    kpis = [
        ("PONTO DE EQUILIBRIO", pe_txt, "Minimo/mes p/ empatar", (15, 23, 42)),
        ("RESULTADO OPERACIONAL", lucro_txt, "Geracao de caixa/mes", (220, 38, 38) if (lucro_val is not None and lucro_val < 0) else (0, 166, 69)),
        ("DINHEIRO NA MESA", pot_txt, "Potencial oculto/mes", (217, 119, 6)),
        ("PONTOS CEGOS", f"{qtd_c} alerta(s)", "Riscos identificados", (220, 38, 38) if qtd_c >= 2 else (0, 166, 69)),
    ]

    for idx, (titulo_k, valor_k, nota_k, cor_v) in enumerate(kpis):
        xk = 12 + idx * (card_w + gap_w)
        pdf.set_fill_color(248, 250, 252)
        pdf.set_draw_color(226, 232, 240)
        pdf.rect(xk, y_kpi, card_w, card_h, "DF")

        pdf.set_xy(xk + 2.5, y_kpi + 2.5)
        pdf.set_font("Helvetica", "B", 6.8)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(card_w - 5, 3.8, pdf_safe(titulo_k), ln=1)

        pdf.set_x(xk + 2.5)
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.set_text_color(*cor_v)
        pdf.cell(card_w - 5, 5.5, pdf_safe(valor_k), ln=1)

        pdf.set_x(xk + 2.5)
        pdf.set_font("Helvetica", "", 6.8)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(card_w - 5, 3.8, pdf_safe(nota_k), ln=1)

    pdf.set_y(y_kpi + card_h + 4.5)

    # 3. BENCHMARK SETORIAL
    y_b = pdf.get_y()
    texto_bench = (
        f"Empresas de alta performance no segmento {bench.get('segmento')} operam com margem acima de "
        f"{int(bench.get('margem_bench', 32))}% e fechamento de {int(bench.get('conv_bench', 24))}%. "
        f"{bench.get('alerta', '')}"
    )
    linhas_bench = max(2, (len(texto_bench) // 98) + 1)
    bench_h = 10 + (linhas_bench * 4.2)

    pdf.set_fill_color(239, 246, 255)
    pdf.rect(12, y_b, 186, bench_h, "F")
    pdf.set_fill_color(29, 78, 216)
    pdf.rect(12, y_b, 2.5, bench_h, "F")

    pdf.set_xy(17, y_b + 2.5)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(29, 78, 216)
    cnae_hdr = f" - CNAE: {dados['cnae'][:60]}" if dados.get("cnae") else ""
    pdf.cell(177, 4.5, pdf_safe(f"BENCHMARK SETORIAL{cnae_hdr}"), ln=1)

    pdf.set_x(17)
    pdf.set_font("Helvetica", "", 8.2)
    pdf.set_text_color(30, 58, 138)
    pdf.multi_cell(177, 4.2, pdf_safe(texto_bench))
    pdf.set_y(y_b + bench_h + 5)

    # 4. RADAR DE PONTOS CEGOS & RISCOS DE CAIXA
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(186, 6, pdf_safe("RADAR DE PONTOS CEGOS & RISCOS DE CAIXA"), ln=1)
    pdf.ln(1)

    pontos_lista = diag.get("pontos_cegos", [])
    if not pontos_lista:
        y_ok = pdf.get_y()
        pdf.set_fill_color(236, 253, 245)
        pdf.rect(12, y_ok, 186, 12, "F")
        pdf.set_fill_color(0, 200, 83)
        pdf.rect(12, y_ok, 2.5, 12, "F")
        pdf.set_xy(17, y_ok + 3.5)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(6, 95, 70)
        pdf.cell(176, 5, pdf_safe("Nenhum ponto cego critico sinalizado. Foco total na captura do potencial oculto e metas comerciais."), ln=1)
        pdf.set_y(y_ok + 15)
    else:
        for item in pontos_lista:
            desc_txt = item.get("descricao", "")
            linhas_desc = max(1, (len(desc_txt) // 95) + 1)
            item_h = 8.5 + (linhas_desc * 4.1)

            if pdf.get_y() + item_h > 272:
                pdf.add_page()

            y_item = pdf.get_y()
            pdf.set_fill_color(254, 242, 242)
            pdf.rect(12, y_item, 186, item_h, "F")
            pdf.set_fill_color(239, 68, 68)
            pdf.rect(12, y_item, 2.2, item_h, "F")

            pdf.set_xy(17, y_item + 2)
            pdf.set_font("Helvetica", "B", 8.8)
            pdf.set_text_color(185, 28, 28)
            pdf.cell(177, 4.5, pdf_safe(f"[{item.get('severidade', 'ALTO')}] {item.get('titulo', '')}"), ln=1)

            pdf.set_x(17)
            pdf.set_font("Helvetica", "", 8.1)
            pdf.set_text_color(51, 65, 85)
            pdf.multi_cell(177, 4.0, pdf_safe(desc_txt))
            pdf.set_y(y_item + item_h + 2.5)

    # 5. ENGENHARIA DE METAS COMERCIAIS
    if pdf.get_y() + 34 > 272:
        pdf.add_page()

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(186, 6, pdf_safe(f"ENGENHARIA DE METAS PARA BATER {fmt_moeda(diag.get('meta_fat'))}/MES"), ln=1)
    pdf.ln(1)

    y_m = pdf.get_y()
    metas_boxes = [
        ("VENDAS NO MES", f"{fmt_num(diag.get('vendas_necessarias_mes'))} fechamentos"),
        ("OPORTUNIDADES/MES", f"{fmt_num(diag.get('oportunidades_mes'))} orcamentos"),
        ("RITMO POR VENDEDOR", f"{diag.get('contatos_dia_por_vendedor', 30)} contatos/dia"),
        ("CADENCIA SEMANAL", f"{diag.get('visitas_semana_por_vendedor', 20)} visitas/reunioes"),
    ]
    for idx, (m_lbl, m_val) in enumerate(metas_boxes):
        xm = 12 + idx * (card_w + gap_w)
        pdf.set_fill_color(248, 250, 252)
        pdf.set_draw_color(203, 213, 225)
        pdf.rect(xm, y_m, card_w, 17, "DF")

        pdf.set_xy(xm + 2.5, y_m + 2.5)
        pdf.set_font("Helvetica", "B", 6.8)
        pdf.set_text_color(100, 116, 139)
        pdf.cell(card_w - 5, 3.8, pdf_safe(m_lbl), ln=1)

        pdf.set_x(xm + 2.5)
        pdf.set_font("Helvetica", "B", 9.2)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(card_w - 5, 5.5, pdf_safe(m_val), ln=1)

    pdf.set_y(y_m + 21)

    # 6. PLANO DE AÇÃO & SESSÃO ESTRATÉGICA + QR CODE WHATSAPP
    if pdf.get_y() + 62 > 274:
        pdf.add_page()

    y_cta = pdf.get_y() + 2
    cta_h = 56
    pdf.set_fill_color(15, 46, 28)
    pdf.rect(12, y_cta, 186, cta_h, "F")
    pdf.set_fill_color(0, 200, 83)
    pdf.rect(12, y_cta, 3, cta_h, "F")

    wpp_destino = normalizar_telefone_br(WHATSAPP_CONSULTOR)
    link_wpp_pdf = f"https://wa.me/{wpp_destino}?text={urllib.parse.quote(diag.get('wpp_msg', ''))}"

    pdf.set_xy(18, y_cta + 3.5)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(254, 240, 138)
    pdf.cell(128, 4.2, pdf_safe("SESSAO DE DIAGNOSTICO COMERCIAL & CAIXA (20 MIN - GRATUITA)"), ln=1)

    pdf.set_x(18)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(0, 200, 83)
    pdf.cell(128, 5.5, pdf_safe("ENTREGAVEIS DA SESSAO COM O ESPECIALISTA:"), ln=1, link=link_wpp_pdf)

    pdf.set_x(18)
    pdf.set_font("Helvetica", "", 7.9)
    pdf.set_text_color(235, 242, 238)
    pdf.multi_cell(
        128, 3.9,
        pdf_safe(
            "1. Revisao da Margem & Ponto de Equilibrio: estancamento imediato de vazamentos.\n"
            "2. Ajuste do Funil Diario: metas de contatos/dia e visitas semanais da equipe.\n"
            f"3. Plano de Acao 30 Dias: roteiro para capturar {fmt_moeda(diag.get('potencial_oculto'))}/mes na mesa."
        )
    )

    y_num = y_cta + 43
    pdf.set_fill_color(24, 68, 42)
    pdf.rect(18, y_num, 126, 8.5, "F")
    pdf.set_xy(20, y_num + 1.8)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(122, 5, pdf_safe(f"Aponte a camera p/ QR Code ou fale no WhatsApp: {WHATSAPP_CONSULTOR}"), link=link_wpp_pdf)

    pdf.set_fill_color(255, 255, 255)
    pdf.rect(152, y_cta + 9, 36, 36, "F")
    qr_ok = False
    if os.path.exists(qr_path):
        try:
            pdf.image(qr_path, x=153.5, y=y_cta + 10.5, w=33, h=33, link=link_wpp_pdf)
            qr_ok = True
        except Exception:
            qr_ok = False
    if not qr_ok:
        pdf.set_xy(152, y_cta + 24)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(15, 46, 28)
        pdf.cell(36, 4, pdf_safe("QR WhatsApp"), align="C")

    try:
        raw_out = pdf.output()
    except TypeError:
        raw_out = pdf.output(dest="S")

    if isinstance(raw_out, str):
        if not raw_out:
            raw_out = pdf.output(dest="S")
        pdf_bytes = raw_out.encode("latin-1")
    else:
        pdf_bytes = bytes(raw_out)

    resp = make_response(pdf_bytes)
    resp.headers["Content-Type"] = "application/pdf"
    resp.headers["Content-Disposition"] = f'attachment; filename="Laudo_Executivo_{cnpj_limpo}.pdf"'
    return resp


# ==============================================================================
# PAINEL ADMINISTRATIVO (MINI-CRM)
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
    rows = []
    for r in cur.fetchall():
        item = dict(r)
        diag_item = json.loads(item.get("diagnostico_json") or "{}")
        item["link_wpp_abordagem"] = gerar_link_abordagem_cliente(item, diag_item, tipo="novo")
        rows.append(item)
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
# TEMPLATES HTML
# ==============================================================================
TEMPLATE_DIAGNOSTICO = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa — Diagnóstico Financeiro e Comercial</title>
    <link rel="icon" href="/static/logo.png" type="image/png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root { --primary: #00C853; --primary-dark: #00A645; --bg: #F1F6F3; --card: #FFFFFF; --text: #0F172A; --muted: #64748B; --border: #E2E8F0; --danger: #EF4444; }
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: var(--bg); color: var(--text); min-height: 100vh; display: flex; justify-content: center; padding: 24px 14px; }
        .container { width: 100%; max-width: 560px; background: var(--card); border-radius: 20px; padding: 28px 24px; box-shadow: 0 12px 35px rgba(15, 23, 42, 0.06); border: 1px solid #E6EDE9; }
        
        .topbar { display: grid; grid-template-columns: 40px 1fr 40px; align-items: center; margin-bottom: 24px; }
        .brand-center { grid-column: 2; display: flex; justify-content: center; align-items: center; }
        .brand-center img { height: 76px; width: auto; object-fit: contain; filter: drop-shadow(0 4px 10px rgba(0,200,83,0.15)); }
        .btn-sair { grid-column: 3; justify-self: end; font-size: 13px; color: var(--muted); text-decoration: none; font-weight: 600; }

        .progress-header { display: flex; justify-content: space-between; font-size: 11px; font-weight: 800; color: var(--primary-dark); letter-spacing: 0.5px; margin-bottom: 8px; text-transform: uppercase; }
        .progress-track { width: 100%; height: 6px; background: #E2ECE6; border-radius: 99px; overflow: hidden; margin-bottom: 24px; }
        .progress-fill { height: 100%; background: var(--primary); width: 25%; transition: width 0.35s ease; border-radius: 99px; }

        .step { display: none; animation: fadeIn 0.25s ease; }
        .step.active { display: block; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

        h1 { font-size: 22px; font-weight: 800; color: var(--text); margin-bottom: 6px; }
        .subtitle { font-size: 14px; color: var(--muted); line-height: 1.5; margin-bottom: 20px; }

        .field { margin-bottom: 16px; }
        label { display: flex; justify-content: space-between; align-items: center; font-size: 13px; font-weight: 700; color: #1E293B; margin-bottom: 6px; }
        .badge-req { font-size: 11px; color: #00A645; background: #DCFCE7; padding: 2px 7px; border-radius: 6px; font-weight: 700; }
        .badge-opt { font-size: 11px; color: #64748B; background: #F1F5F9; padding: 2px 7px; border-radius: 6px; font-weight: 600; }

        input[type="text"], input[type="number"], input[type="tel"], select { width: 100%; padding: 13px 14px; border-radius: 12px; border: 1.5px solid var(--border); font-size: 15px; color: var(--text); background: #fff; outline: none; transition: border-color 0.2s, background-color 0.2s; }
        input:focus, select:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(0, 200, 83, 0.14); }
        input.input-erro, select.input-erro { border-color: var(--danger) !important; background: #FEF2F2 !important; box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.14) !important; }
        .status-cnpj { font-size: 12.5px; font-weight: 600; margin-top: 6px; min-height: 18px; }
        .err-msg { font-size: 12px; color: var(--danger); font-weight: 700; margin-top: 5px; display: none; }
        .err-msg.visible { display: block; }

        .ramo-box { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; padding: 12px 14px; font-size: 12.5px; color: #334155; line-height: 1.45; margin-bottom: 20px; }
        .calc-toggle { display: inline-flex; align-items: center; gap: 6px; margin-top: 7px; font-size: 12.5px; font-weight: 700; color: #00A645; background: #ECFDF5; border: 1px solid #A7F3D0; padding: 6px 11px; border-radius: 8px; cursor: pointer; }
        .calc-box { display: none; margin-top: 10px; background: #F8FAFC; border: 1.5px dashed #94A3B8; border-radius: 12px; padding: 14px; }
        .calc-box.open { display: block; }
        .calc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 8px; }
        .calc-box input { padding: 9px 11px; font-size: 13.5px; }
        .btn-aplicar-calc { margin-top: 10px; width: 100%; padding: 9px; border: none; border-radius: 9px; background: #0F172A; color: #fff; font-weight: 700; font-size: 13px; cursor: pointer; }

        .cegos-box { background: #FFF8F6; border: 1.5px solid #FED7AA; border-radius: 14px; padding: 14px; margin-top: 18px; margin-bottom: 18px; }
        .cegos-title { font-size: 13px; font-weight: 800; color: #9A3412; margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
        .cegos-sub { font-size: 12px; color: #7C2D12; margin-bottom: 10px; line-height: 1.4; }
        .cego-check { display: flex; align-items: flex-start; gap: 10px; background: #fff; border: 1.5px solid #E2E8F0; border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; cursor: pointer; transition: all 0.15s ease; }
        .cego-check:hover { border-color: #F97316; }
        .cego-check.checked { border-color: #EF4444; background: #FEF2F2; }
        .cego-check input[type="checkbox"] { width: 18px; height: 18px; margin-top: 1px; accent-color: #EF4444; flex-shrink: 0; cursor: pointer; }
        .cego-check span { font-size: 13px; font-weight: 600; color: #1E293B; line-height: 1.35; }

        .teaser-card { background: linear-gradient(135deg, #0F172A, #1E293B); color: #fff; border-radius: 16px; padding: 18px; margin-bottom: 20px; }
        .teaser-badge { display: inline-block; background: rgba(0,200,83,0.2); color: #4ADE80; font-size: 11px; font-weight: 800; padding: 4px 10px; border-radius: 99px; margin-bottom: 10px; }
        .teaser-blur-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
        .teaser-metric { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 10px; }
        .teaser-metric small { display: block; font-size: 11px; color: #94A3B8; margin-bottom: 4px; }
        .teaser-metric strong { font-size: 16px; color: #4ADE80; filter: blur(5px); }

        .btn-row { display: flex; gap: 10px; margin-top: 8px; }
        .btn-primary { flex: 1; background: var(--primary); color: #fff; border: none; border-radius: 12px; padding: 15px 18px; font-size: 15.5px; font-weight: 800; cursor: pointer; box-shadow: 0 6px 18px rgba(0, 200, 83, 0.25); }
        .btn-primary:hover { background: var(--primary-dark); }
        .btn-back { background: #F1F5F9; color: #475569; border: none; border-radius: 12px; padding: 15px 16px; font-size: 14px; font-weight: 700; cursor: pointer; }
        .footer-lgpd { margin-top: 22px; padding-top: 16px; border-top: 1px solid #EEF2F0; text-align: center; font-size: 11.5px; color: var(--muted); line-height: 1.5; }
        .footer-lgpd .box-lgpd { background: #F8FAFC; border-radius: 10px; padding: 8px 12px; margin-bottom: 10px; }
    </style>
</head>
<body>
<div class="container">
    <div class="topbar">
        <div></div>
        <div class="brand-center">
            <img src="/static/logo.png" alt="Doutor Caixa" onerror="this.style.display='none';">
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

    <form id="form-diag" method="POST" action="/gerar-laudo" novalidate onsubmit="return validarFinal(event)">
        <input type="hidden" name="cidade" id="inp_cidade">
        <input type="hidden" name="uf" id="inp_uf">
        <input type="hidden" name="cnae" id="inp_cnae">
        <input type="hidden" name="origem" id="inp_origem" value="{{ origem }}">

        <!-- ETAPA 1 -->
        <div class="step active" id="step-1">
            <h1>1. Dados da Empresa</h1>
            <p class="subtitle">Digite o CNPJ para localizarmos sua empresa automaticamente.</p>
            <div class="field">
                <label>CNPJ Válido (Somente números) <span class="badge-req">Obrigatório</span></label>
                <input type="text" id="cnpj" name="cnpj" placeholder="00.000.000/0000-00" maxlength="18" inputmode="numeric">
                <div class="status-cnpj" id="cnpj_status"></div>
                <div class="err-msg" id="err_cnpj">⚠️ Informe um CNPJ válido com 14 dígitos.</div>
            </div>
            <div class="field">
                <label>Nome da Empresa <span class="badge-req">Obrigatório</span></label>
                <input type="text" id="empresa_nome" name="empresa" placeholder="Ex: Distribuidora Recife Ltda">
                <div class="err-msg" id="err_empresa_nome">⚠️ Informe o nome da empresa.</div>
            </div>
            <div class="field">
                <label>Ramo de Atuação / Modelo de Venda</label>
                <select id="ramo" name="ramo" onchange="atualizarDescRamo()">
                    <option value="Comércio / Varejo / Distribuição (Produtos)">Comércio / Varejo / Distribuição (Produtos)</option>
                    <option value="Serviços B2B / Consultoria / Agência / TI">Serviços B2B / Consultoria / Agência / TI</option>
                    <option value="Clínicas / Saúde / Estética">Clínicas / Saúde / Estética</option>
                    <option value="Indústria / Fábrica / Máquinas">Indústria / Fábrica / Máquinas</option>
                    <option value="Recorrência / SaaS / Assinaturas">Recorrência / SaaS / Assinaturas</option>
                </select>
            </div>
            <div class="ramo-box" id="ramo-desc">
                🛒 <strong>Comércio e Varejo:</strong> Foco em giro de estoque, movimento diário e proteção de margem.
            </div>
            <div class="btn-row">
                <button type="button" class="btn-primary" onclick="avancarEtapa1()">Avançar →</button>
            </div>
        </div>

        <!-- ETAPA 2 -->
        <div class="step" id="step-2">
            <h1>2. Raio-X Financeiro</h1>
            <p class="subtitle">Preencha os números que souber e marque os gargalos financeiros que percebe hoje.</p>
            <div class="field">
                <label>Faturamento Mensal Médio (R$) <span class="badge-opt">Opcional</span></label>
                <input type="text" id="faturamento" name="faturamento" placeholder="Ex: 120.000,00" class="mask-moeda">
            </div>
            <div class="field">
                <label>Margem de Contribuição Média (%) <span class="badge-opt">Opcional</span></label>
                <input type="text" id="margem" name="margem" placeholder="Ex: 35">
                <button type="button" class="calc-toggle" onclick="toggleCalcMargem()">🧮 Não sei minha margem % — Calcular em 10s</button>
                <div class="calc-box" id="calc-margem-box">
                    <div style="font-size:12px; font-weight:700;">Calculadora Rápida de Margem</div>
                    <div class="calc-grid">
                        <div><label style="font-size:11px;">Preço de Venda (R$)</label><input type="text" id="calc_preco" class="mask-moeda"></div>
                        <div><label style="font-size:11px;">Custo Direto (R$)</label><input type="text" id="calc_custo" class="mask-moeda"></div>
                    </div>
                    <div style="margin-top:6px;"><label style="font-size:11px;">Impostos + Comissões (%)</label><input type="text" id="calc_imp"></div>
                    <button type="button" class="btn-aplicar-calc" onclick="aplicarCalculoMargem()">Preencher Margem Automaticamente ✓</button>
                </div>
            </div>
            <div class="field">
                <label>Custos Fixos Mensais Totais (R$) <span class="badge-opt">Opcional</span></label>
                <input type="text" id="custos_fixos" name="custos_fixos" placeholder="Ex: 38.000,00" class="mask-moeda">
            </div>

            <div class="cegos-box">
                <div class="cegos-title">🚨 Pontos Cegos Financeiros (Marque o que acontece hoje)</div>
                <div class="cegos-sub">Selecione os sintomas abaixo para incluirmos no seu diagnóstico:</div>
                {% for cod, lbl in gargalos_fin %}
                <label class="cego-check" onclick="toggleCheckStyle(this)">
                    <input type="checkbox" name="gargalos" value="{{ cod }}">
                    <span>{{ lbl }}</span>
                </label>
                {% endfor %}
            </div>

            <div class="btn-row">
                <button type="button" class="btn-back" onclick="irParaEtapa(1)">← Voltar</button>
                <button type="button" class="btn-primary" onclick="irParaEtapa(3)">Avançar →</button>
            </div>
        </div>

        <!-- ETAPA 3 -->
        <div class="step" id="step-3">
            <h1>3. Motor Comercial & Metas</h1>
            <p class="subtitle">Cruzamento de oportunidades, capacidade da equipe e gargalos de vendas.</p>
            <div class="field"><label>Ticket Médio por Venda (R$) <span class="badge-opt">Opcional</span></label><input type="text" id="ticket_medio" name="ticket_medio" placeholder="Ex: 2.500,00" class="mask-moeda"></div>
            <div class="field"><label>Oportunidades / Orçamentos por Mês <span class="badge-opt">Opcional</span></label><input type="number" id="leads_mes" name="leads_mes" placeholder="Ex: 120"></div>
            <div class="field"><label>Taxa de Fechamento (%) <span class="badge-opt">Opcional</span></label><input type="text" id="taxa_conv" name="taxa_conv" placeholder="Ex: 20"></div>
            <div class="field"><label>Equipe Comercial (Vendedores) <span class="badge-opt">Opcional</span></label><input type="number" id="vendedores" name="vendedores" value="1" min="1"></div>
            <div class="field"><label>Meta de Faturamento (R$/mês) <span class="badge-opt">Opcional</span></label><input type="text" id="meta_fat" name="meta_fat" placeholder="Ex: 150.000,00" class="mask-moeda"></div>

            <div class="cegos-box">
                <div class="cegos-title">🎯 Pontos Cegos Comerciais (Marque os gargalos de vendas)</div>
                <div class="cegos-sub">Estes pontos entrarão no seu plano de ação comercial:</div>
                {% for cod, lbl in gargalos_com %}
                <label class="cego-check" onclick="toggleCheckStyle(this)">
                    <input type="checkbox" name="gargalos" value="{{ cod }}">
                    <span>{{ lbl }}</span>
                </label>
                {% endfor %}
            </div>

            <div class="btn-row">
                <button type="button" class="btn-back" onclick="irParaEtapa(2)">← Voltar</button>
                <button type="button" class="btn-primary" onclick="prepararEtapa4()">Ver Meu Diagnóstico →</button>
            </div>
        </div>

        <!-- ETAPA 4 -->
        <div class="step" id="step-4">
            <h1>4. Liberar Laudo Completo</h1>
            <p class="subtitle">Diagnóstico pronto. Preencha seus dados obrigatórios para desbloquear.</p>
            <div class="teaser-card">
                <div class="teaser-badge">⚡ DIAGNÓSTICO PRONTO</div>
                <div style="font-size:13.5px; color:#E2E8F0;" id="teaser-resumo">✅ Encontramos pontos cegos e calculamos seu ponto de equilíbrio.</div>
                <div class="teaser-blur-grid">
                    <div class="teaser-metric"><small>Ponto de Equilíbrio</small><strong>R$ 84.500</strong></div>
                    <div class="teaser-metric"><small>Potencial Oculto</small><strong>R$ 27.900</strong></div>
                </div>
            </div>
            <div class="field">
                <label>Seu Nome Completo <span class="badge-req">Obrigatório</span></label>
                <input type="text" id="solicitante" name="solicitante" placeholder="Ex: Carlos Silva">
                <div class="err-msg" id="err_solicitante">⚠️ Preencha seu nome completo para liberar o laudo.</div>
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
                <div class="err-msg" id="err_cargo">⚠️ Selecione seu cargo na empresa.</div>
            </div>
            <div class="field">
                <label>WhatsApp com DDD <span class="badge-req">Obrigatório</span></label>
                <input type="tel" id="whatsapp" name="whatsapp" placeholder="(81) 99999-9999" maxlength="15" inputmode="tel">
                <div class="err-msg" id="err_whatsapp">⚠️ Informe um número de WhatsApp válido com DDD.</div>
            </div>
            <div class="btn-row">
                <button type="button" class="btn-back" onclick="irParaEtapa(3)">← Voltar</button>
                <button type="submit" class="btn-primary">🔓 Liberar Laudo Agora</button>
            </div>
        </div>
    </form>
    <div class="footer-lgpd"><div class="box-lgpd">🔒 <strong>Sigilo LGPD</strong></div>Doutor Caixa — <strong>MaqTrak</strong></div>
</div>

<script>
    let ultimoCnpjBuscado = "";

    function toggleCheckStyle(labelEl) {
        setTimeout(() => {
            const cb = labelEl.querySelector('input[type="checkbox"]');
            if (cb && cb.checked) labelEl.classList.add('checked');
            else labelEl.classList.remove('checked');
        }, 10);
    }

    function atualizarDescRamo() {
        const val = document.getElementById('ramo').value;
        const box = document.getElementById('ramo-desc');
        if (val.includes('Clínicas')) {
            box.innerHTML = '🩺 <strong>Saúde & Clínicas:</strong> Foco em conversão de avaliações, ticket por procedimento e margem líquida.';
        } else if (val.includes('Serviços B2B')) {
            box.innerHTML = '💼 <strong>Serviços B2B & Agências:</strong> Foco em margem por hora/contrato, cadência comercial e taxa de fechamento.';
        } else if (val.includes('Indústria')) {
            box.innerHTML = '🏭 <strong>Indústria & Máquinas:</strong> Foco em margem industrial, ciclo longo de vendas e previsibilidade de pipeline.';
        } else if (val.includes('Recorrência')) {
            box.innerHTML = '🔄 <strong>Recorrência & Assinaturas:</strong> Foco em LTV, retenção de base e eficiência na aquisição de clientes.';
        } else {
            box.innerHTML = '🛒 <strong>Comércio e Varejo:</strong> Foco em giro de estoque, movimento diário e proteção de margem.';
        }
    }

    function sugerirRamoPorCnae(cnaeTxt) {
        if (!cnaeTxt) return;
        const t = cnaeTxt.toLowerCase();
        const sel = document.getElementById('ramo');
        if (t.includes('odont') || t.includes('médic') || t.includes('saúde') || t.includes('clínica') || t.includes('estética') || t.includes('hospital')) {
            sel.value = 'Clínicas / Saúde / Estética';
        } else if (t.includes('software') || t.includes('tecnologia') || t.includes('informática') || t.includes('consultoria') || t.includes('publicidade') || t.includes('agência')) {
            sel.value = 'Serviços B2B / Consultoria / Agência / TI';
        } else if (t.includes('indústria') || t.includes('fabricação') || t.includes('máquina') || t.includes('metal') || t.includes('engenharia')) {
            sel.value = 'Indústria / Fábrica / Máquinas';
        } else if (t.includes('educação') || t.includes('ensino') || t.includes('telecom') || t.includes('assinatura')) {
            sel.value = 'Recorrência / SaaS / Assinaturas';
        }
        atualizarDescRamo();
    }

    function marcarErro(idInput, idErr, mostrar) {
        const el = document.getElementById(idInput);
        const err = document.getElementById(idErr);
        if (!el || !err) return;
        if (mostrar) {
            el.classList.add('input-erro');
            err.classList.add('visible');
        } else {
            el.classList.remove('input-erro');
            err.classList.remove('visible');
        }
    }

    ['cnpj', 'empresa_nome', 'solicitante', 'cargo', 'whatsapp'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.addEventListener('input', () => marcarErro(id, 'err_' + id, false));
            el.addEventListener('change', () => marcarErro(id, 'err_' + id, false));
        }
    });

    function validarCNPJ(c) {
        c = c.replace(/[^\d]+/g,'');
        if(c.length!==14 || /^(\d)\1+$/.test(c)) return false;
        let t = c.length - 2, n = c.substring(0, t), d = c.substring(t), s = 0, p = t - 7;
        for (let i = t; i >= 1; i--) { s += n.charAt(t - i) * p--; if (p < 2) p = 9; }
        let r = s % 11 < 2 ? 0 : 11 - s % 11;
        if (r != d.charAt(0)) return false;
        t++; n = c.substring(0, t); s = 0; p = t - 7;
        for (let i = t; i >= 1; i--) { s += n.charAt(t - i) * p--; if (p < 2) p = 9; }
        r = s % 11 < 2 ? 0 : 11 - s % 11;
        return r == d.charAt(1);
    }

    async function consultarBrasilAPI(cnpj) {
        if (cnpj === ultimoCnpjBuscado) return;
        ultimoCnpjBuscado = cnpj;
        const st = document.getElementById('cnpj_status'), nom = document.getElementById('empresa_nome');
        st.style.color = '#0284C7';
        st.innerText = '⏳ Buscando empresa nas bases oficiais...';
        try {
            const res = await fetch(`/api/cnpj/${cnpj}`);
            const d = await res.json();
            if(d.ok && d.nome) {
                nom.value = d.nome;
                marcarErro('empresa_nome', 'err_empresa_nome', false);
                document.getElementById('inp_cidade').value = d.municipio || '';
                document.getElementById('inp_uf').value = d.uf || '';
                document.getElementById('inp_cnae').value = d.cnae || '';
                sugerirRamoPorCnae(d.cnae || '');
                st.style.color = '#00A645';
                st.innerText = `✅ Empresa encontrada: ${d.nome} (${d.municipio || ''}/${d.uf || ''})`;
            } else {
                st.style.color = '#D97706';
                st.innerText = '⚠️ CNPJ válido, mas nome não retornado. Digite manualmente.';
            }
        } catch(e) {
            st.style.color = '#DC2626';
            st.innerText = '⚠️ Erro de conexão ao buscar CNPJ. Digite o nome manualmente.';
        }
    }

    const cInp = document.getElementById('cnpj');
    cInp.addEventListener('input', e => {
        let v = e.target.value.replace(/\D/g,'').slice(0,14);
        v = v.replace(/^(\d{2})(\d)/,'$1.$2').replace(/^(\d{2})\.(\d{3})(\d)/,'$1.$2.$3').replace(/\.(\d{3})(\d)/,'.$1/$2').replace(/(\d{4})(\d)/,'$1-$2');
        e.target.value = v;
        let d = v.replace(/\D/g,'');
        if(d.length===14 && validarCNPJ(d)) {
            consultarBrasilAPI(d);
        } else {
            document.getElementById('cnpj_status').innerText = '';
        }
    });

    document.querySelectorAll('.mask-moeda').forEach(i => {
        i.addEventListener('input', e => {
            let v = e.target.value.replace(/\D/g,'');
            if(!v) { e.target.value = ''; return; }
            e.target.value = (parseInt(v,10)/100).toFixed(2).replace('.',',').replace(/(\d)(?=(\d{3})+(?!\d))/g,'$1.');
        });
    });

    document.getElementById('whatsapp').addEventListener('input', e => {
        let v = e.target.value.replace(/\D/g,'').slice(0,11);
        if(v.length>6) v=v.replace(/^(\d{2})(\d{5})(\d{0,4})/,'($1) $2-$3');
        else if(v.length>2) v=v.replace(/^(\d{2})(\d{0,5})/,'($1) $2');
        e.target.value = v;
    });

    function toggleCalcMargem() { document.getElementById('calc-margem-box').classList.toggle('open'); }
    function parseBRL(s) { return s ? parseFloat(s.replace(/\./g,'').replace(',','.').replace(/[^\d.-]/g,'')) || 0 : 0; }
    function aplicarCalculoMargem() {
        let p = parseBRL(document.getElementById('calc_preco').value), c = parseBRL(document.getElementById('calc_custo').value), i = parseBRL(document.getElementById('calc_imp').value);
        if(!p) { alert('Informe o preço de venda'); return; }
        let m = Math.max(1, (((p - c) / p) * 100) - i);
        document.getElementById('margem').value = m.toFixed(1).replace('.',',');
        document.getElementById('calc-margem-box').classList.remove('open');
    }

    function irParaEtapa(n) {
        document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
        document.getElementById(`step-${n}`).classList.add('active');
        const tit = {1: ["ETAPA 1 DE 4 — DADOS DA EMPRESA", "25%"], 2: ["ETAPA 2 DE 4 — RAIO-X FINANCEIRO", "50%"], 3: ["ETAPA 3 DE 4 — MOTOR COMERCIAL", "75%"], 4: ["ETAPA 4 DE 4 — LIBERAR LAUDO", "100%"]};
        document.getElementById('step-label').innerText = tit[n][0]; document.getElementById('step-pct').innerText = tit[n][1]; document.getElementById('progress-fill').style.width = tit[n][1];
        window.scrollTo({top:0, behavior:'smooth'});
    }

    function avancarEtapa1() {
        let d = cInp.value.replace(/\D/g,''), emp = document.getElementById('empresa_nome').value.trim();
        let cnpjOk = (d.length === 14 && validarCNPJ(d));
        let empOk = (emp.length > 0);
        marcarErro('cnpj', 'err_cnpj', !cnpjOk);
        marcarErro('empresa_nome', 'err_empresa_nome', !empOk);
        if (!cnpjOk) { document.getElementById('cnpj').focus(); return; }
        if (!empOk) { document.getElementById('empresa_nome').focus(); return; }
        fetch('/api/lead-parcial', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cnpj:d, empresa:emp, cidade:document.getElementById('inp_cidade').value, uf:document.getElementById('inp_uf').value, cnae:document.getElementById('inp_cnae').value, ramo:document.getElementById('ramo').value, origem:document.getElementById('inp_origem').value})}).catch(()=>{});
        irParaEtapa(2);
    }

    function prepararEtapa4() {
        const marcados = document.querySelectorAll('input[name="gargalos"]:checked').length;
        const emp = document.getElementById('empresa_nome').value.trim() || 'sua empresa';
        const resumo = document.getElementById('teaser-resumo');
        if (marcados > 0) {
            resumo.innerText = `✅ Cruzamos os dados da ${emp} com os ${marcados} gargalo(s) selecionado(s) e calculamos seu ponto de equilíbrio.`;
        } else {
            resumo.innerText = `✅ Cruzamos os dados da ${emp} com o benchmark do setor e calculamos seu ponto de equilíbrio.`;
        }
        irParaEtapa(4);
    }

    function validarFinal(e) {
        const nomeEl = document.getElementById('solicitante');
        const cargoEl = document.getElementById('cargo');
        const wppEl = document.getElementById('whatsapp');

        const nomeOk = nomeEl.value.trim().length >= 2;
        const cargoOk = cargoEl.value.trim() !== "";
        const wppOk = wppEl.value.replace(/\D/g, '').length >= 10;

        marcarErro('solicitante', 'err_solicitante', !nomeOk);
        marcarErro('cargo', 'err_cargo', !cargoOk);
        marcarErro('whatsapp', 'err_whatsapp', !wppOk);

        if (!nomeOk || !cargoOk || !wppOk) {
            if (e) e.preventDefault();
            if (!nomeOk) nomeEl.focus();
            else if (!cargoOk) cargoEl.focus();
            else wppEl.focus();
            return false;
        }
        return true;
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
    <link rel="icon" href="/static/logo.png" type="image/png">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Plus Jakarta Sans', sans-serif; }
        body { background: #F1F6F3; color: #0F172A; padding: 24px 14px 60px; }
        .wrap { max-width: 820px; margin: 0 auto; }
        .header-card { background: linear-gradient(135deg, #0F172A 0%, #1E293B 100%); color: #fff; border-radius: 20px; padding: 28px; margin-bottom: 18px; box-shadow: 0 12px 30px rgba(15,23,42,0.12); }
        .top-meta { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
        .tag-brand { background: rgba(0,200,83,0.18); color: #4ADE80; font-weight: 800; font-size: 12px; padding: 5px 12px; border-radius: 99px; }
        .btn-print { background: rgba(255,255,255,0.12); color: #fff; border: 1px solid rgba(255,255,255,0.2); padding: 7px 14px; border-radius: 10px; font-size: 12.5px; font-weight: 700; cursor: pointer; text-decoration: none; }
        .header-card h1 { font-size: 24px; font-weight: 800; margin-bottom: 6px; }
        .header-sub { font-size: 13.5px; color: #CBD5E1; line-height: 1.5; }
        .kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 18px; }
        .kpi-card { background: #fff; border-radius: 16px; padding: 18px; border: 1px solid #E2E8F0; }
        .kpi-card small { display: block; font-size: 12px; font-weight: 700; color: #64748B; margin-bottom: 6px; text-transform: uppercase; }
        .kpi-val { font-size: 21px; font-weight: 800; color: #0F172A; }
        .kpi-val.green { color: #00A645; } .kpi-val.red { color: #DC2626; } .kpi-val.amber { color: #D97706; }
        .kpi-note { font-size: 11.5px; color: #64748B; margin-top: 5px; line-height: 1.35; }
        .bench-card { background: #EFF6FF; border: 1.5px solid #BFDBFE; border-radius: 16px; padding: 18px 20px; margin-bottom: 18px; }
        .bench-title { font-size: 13px; font-weight: 800; color: #1D4ED8; text-transform: uppercase; margin-bottom: 6px; }
        .bench-text { font-size: 14px; color: #1E3A8A; line-height: 1.55; }
        .section-card { background: #fff; border-radius: 18px; padding: 24px; border: 1px solid #E2E8F0; margin-bottom: 18px; }
        .section-title { font-size: 18px; font-weight: 800; color: #0F172A; margin-bottom: 14px; }
        .cega-item { border-left: 4px solid #EF4444; background: #FEF2F2; border-radius: 0 12px 12px 0; padding: 14px 16px; margin-bottom: 12px; }
        .cega-ok { border-left: 4px solid #00C853; background: #ECFDF5; border-radius: 0 12px 12px 0; padding: 14px 16px; font-size: 13.5px; color: #065F46; }
        .cega-head { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 5px; }
        .cega-head strong { font-size: 14.5px; color: #0F172A; }
        .sev-badge { font-size: 10.5px; font-weight: 800; padding: 2px 8px; border-radius: 6px; background: #FEE2E2; color: #B91C1C; white-space: nowrap; }
        .cega-desc { font-size: 13.5px; color: #334155; line-height: 1.5; }
        .offer-card { background: linear-gradient(135deg, #064E3B 0%, #0F172A 100%); color: #fff; border-radius: 20px; padding: 26px 24px; margin-bottom: 18px; border: 2px solid #00C853; box-shadow: 0 14px 32px rgba(0, 200, 83, 0.16); }
        .scarcity-pill { display: inline-block; background: #FEF08A; color: #854D0E; font-weight: 800; font-size: 12px; padding: 5px 12px; border-radius: 99px; margin-bottom: 12px; }
        .offer-card h2 { font-size: 21px; font-weight: 800; margin-bottom: 8px; }
        .offer-sub { font-size: 14px; color: #CBD5E1; margin-bottom: 16px; line-height: 1.5; }
        .deliverables { list-style: none; margin-bottom: 20px; }
        .deliverables li { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 11px 14px; margin-bottom: 9px; font-size: 13.5px; color: #F8FAFC; }
        .cta-dual { display: grid; grid-template-columns: 1.35fr 1fr; gap: 12px; }
        @media (max-width: 640px) { .cta-dual { grid-template-columns: 1fr; } }
        .btn-cta-main { display: flex; align-items: center; justify-content: center; text-align: center; background: #00C853; color: #fff; text-decoration: none; font-weight: 800; font-size: 15px; padding: 16px 18px; border-radius: 14px; box-shadow: 0 8px 22px rgba(0,200,83,0.35); transition: transform 0.15s ease, background 0.15s ease; }
        .btn-cta-main:hover { background: #00A645; transform: translateY(-1px); }
        .btn-cta-main.danger { background: #DC2626; box-shadow: 0 8px 22px rgba(220,38,38,0.42); }
        .btn-cta-main.danger:hover { background: #B91C1C; }
        .btn-cta-main.warning { background: #EA580C; box-shadow: 0 8px 22px rgba(234,88,12,0.40); }
        .btn-cta-main.warning:hover { background: #C2410C; }
        .btn-cta-agenda { display: flex; align-items: center; justify-content: center; text-align: center; background: rgba(255,255,255,0.12); color: #fff; border: 1.5px solid rgba(255,255,255,0.35); text-decoration: none; font-weight: 700; font-size: 14px; padding: 15px 16px; border-radius: 14px; }
        .btn-cta-agenda:hover { background: rgba(255,255,255,0.2); }
        .cta-urgency-note { margin-top: 10px; text-align: center; font-size: 11.5px; color: #A7F3D0; font-weight: 600; }
        .plano-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap: 12px; }
        .plano-box { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px; }
        .plano-box small { display: block; font-size: 11.5px; color: #64748B; font-weight: 700; margin-bottom: 4px; }
        .plano-box strong { font-size: 18px; color: #0F172A; font-weight: 800; }
        .footer { text-align: center; font-size: 12px; color: #64748B; margin-top: 24px; line-height: 1.6; }
    </style>
</head>
<body>
<div class="wrap">
    <div class="header-card">
        <div class="top-meta">
            <span class="tag-brand">📊 DOUTOR CAIXA • LAUDO EXECUTIVO</span>
            <a href="/baixar_pdf/{{ lead.cnpj }}" class="btn-print">📄 Baixar PDF Executivo</a>
        </div>
        <h1>{{ lead.empresa }}</h1>
        <div class="header-sub">
            CNPJ: {{ lead.cnpj | cnpj_fmt }} {% if lead.cidade %}• {{ lead.cidade }}/{{ lead.uf }}{% endif %}<br>
            Solicitante: <strong>{{ lead.solicitante }}</strong> ({{ lead.cargo }}) • Segmento: {{ lead.ramo }}
        </div>
    </div>

    <div class="kpi-grid">
        <div class="kpi-card">
            <small>Ponto de Equilíbrio</small>
            <div class="kpi-val">{% if diag.ponto_equilibrio %}{{ diag.ponto_equilibrio | moeda }}{% else %}Não calculável{% endif %}</div>
            <div class="kpi-note">Faturamento mínimo/mês para empatar as contas.</div>
        </div>
        <div class="kpi-card">
            <small>Resultado Operacional</small>
            <div class="kpi-val {% if diag.lucro_atual is not none %}{% if diag.lucro_atual < 0 %}red{% else %}green{% endif %}{% else %}amber{% endif %}">
                {% if diag.lucro_atual is not none %}{{ diag.lucro_atual | moeda }}/mês{% else %}Ponto Cego{% endif %}
            </div>
            <div class="kpi-note">Geração de caixa operacional estimada no mês.</div>
        </div>
        <div class="kpi-card">
            <small>Dinheiro na Mesa (Mês)</small>
            <div class="kpi-val amber">+{{ diag.potencial_oculto | moeda }}</div>
            <div class="kpi-note">Ganho mensal estimado ao alinhar margem e conversão.</div>
        </div>
        <div class="kpi-card">
            <small>Pontos Cegos Detectados</small>
            <div class="kpi-val {% if diag.qtd_cegas >= 2 %}red{% else %}green{% endif %}">{{ diag.qtd_cegas }} alerta(s)</div>
            <div class="kpi-note">Vulnerabilidades financeiras e comerciais identificadas.</div>
        </div>
    </div>

    <div class="bench-card">
        <div class="bench-title">📊 Benchmark Setorial {% if lead.cnae %}— CNAE: {{ lead.cnae }}{% endif %}</div>
        <div class="bench-text">
            Empresas de alta performance no segmento <strong>{{ diag.bench.segmento }}</strong> operam com margem acima de <strong>{{ diag.bench.margem_bench | int }}%</strong> e fechamento de <strong>{{ diag.bench.conv_bench | int }}%</strong>. {{ diag.bench.alerta }}
        </div>
    </div>

    <div class="section-card">
        <div class="section-title">🚨 Radar de Pontos Cegos & Riscos de Caixa</div>
        {% if diag.pontos_cegos %}
            {% for item in diag.pontos_cegos %}
            <div class="cega-item">
                <div class="cega-head">
                    <strong>{{ item.titulo }}</strong>
                    <span class="sev-badge">{{ item.severidade }}</span>
                </div>
                <div class="cega-desc">{{ item.descricao }}</div>
            </div>
            {% endfor %}
        {% else %}
            <div class="cega-ok">
                ✅ Nenhum ponto cego crítico sinalizado. Foco total na captura do potencial oculto de <strong>{{ diag.potencial_oculto | moeda }}/mês</strong> e na execução das metas abaixo.
            </div>
        {% endif %}
    </div>

    <div class="offer-card">
        <div class="scarcity-pill">⚠️ Limitado a 4 empresas por semana na Grande Recife ({{ vagas_restantes }} vagas restantes)</div>
        <h2>Sessão de Diagnóstico Comercial & Caixa (20 min — Gratuita)</h2>
        <p class="offer-sub">Vamos abrir o diagnóstico da <strong>{{ lead.empresa }}</strong> ao vivo com um especialista da MaqTrak para entregar:</p>
        <ul class="deliverables">
            <li><strong>1. Revisão da Margem & Ponto de Equilíbrio:</strong> estancamento imediato de vazamentos de caixa.</li>
            <li><strong>2. Ajuste do Funil Diário:</strong> definição de metas de contatos/dia e visitas semanais.</li>
            <li><strong>3. Plano de Ação de 30 Dias:</strong> roteiro prático para capturar os <strong>{{ diag.potencial_oculto | moeda }}/mês</strong> deixados na mesa.</li>
        </ul>
        <div class="cta-dual">
            <a href="/cta-wpp/{{ lead.cnpj }}" target="_blank" class="btn-cta-main {{ diag.cta_cor }}">
                {{ diag.cta_texto }}
            </a>
            <a href="/cta-agenda/{{ lead.cnpj }}" target="_blank" class="btn-cta-agenda">
                📅 Agendar Sessão via WhatsApp
            </a>
        </div>
        <div class="cta-urgency-note">⏳ Prioridade de atendimento garantida por 24h para o CNPJ {{ lead.cnpj | cnpj_fmt }}</div>
    </div>

    <div class="section-card">
        <div class="section-title">🎯 Engenharia de Metas para Bater {{ diag.meta_fat | moeda }}/mês</div>
        <div class="plano-grid">
            <div class="plano-box"><small>Vendas no Mês</small><strong>{{ diag.vendas_necessarias_mes | num }} fechamentos</strong></div>
            <div class="plano-box"><small>Oportunidades/Mês</small><strong>{{ diag.oportunidades_mes | num }} orçamentos</strong></div>
            <div class="plano-box"><small>Ritmo por Vendedor</small><strong>{{ diag.contatos_dia_por_vendedor }} contatos/dia</strong></div>
            <div class="plano-box"><small>Cadência Semanal</small><strong>{{ diag.visitas_semana_por_vendedor }} visitas/reuniões</strong></div>
        </div>
    </div>

    <div class="footer">
        Diagnóstico gerado em {{ lead.atualizado_em }} • <strong>Doutor Caixa</strong> — Uma solução <strong>MaqTrak</strong>.
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
    <link rel="icon" href="/static/logo.png" type="image/png">
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
    <link rel="icon" href="/static/logo.png" type="image/png">
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
        .lead-card { background: #fff; border-radius: 16px; padding: 18px; border: 1px solid #E2E8F0; display: flex; flex-direction: column; justify-content: space-between; }
        .lead-card.incompleto { border-left: 5px solid #F59E0B; background: #FFFDF7; }
        .lead-card.quente { border-left: 5px solid #EF4444; }
        .badges { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
        .badge { font-size: 11px; font-weight: 800; padding: 3px 8px; border-radius: 6px; }
        .b-inc { background: #FEF3C7; color: #B45309; } .b-comp { background: #DCFCE7; color: #15803D; } .b-hot { background: #FEE2E2; color: #B91C1C; }
        .lead-title { font-size: 16px; font-weight: 800; color: #0F172A; margin-bottom: 3px; }
        .lead-meta { font-size: 12.5px; color: #64748B; margin-bottom: 12px; line-height: 1.45; }
        .lead-nums { background: #F8FAFC; border-radius: 10px; padding: 10px 12px; font-size: 12.5px; margin-bottom: 12px; line-height: 1.55; }
        .crm-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
        .crm-select { flex: 1; padding: 8px 10px; border-radius: 9px; border: 1.5px solid #CBD5E1; font-size: 12.5px; font-weight: 700; background: #fff; }
        .save-ok { font-size: 11.5px; font-weight: 700; color: #00A645; opacity: 0; transition: opacity 0.2s; }
        .card-actions { display: flex; gap: 8px; }
        .btn-act { flex: 1; text-align: center; padding: 9px 10px; border-radius: 9px; font-size: 12.5px; font-weight: 700; text-decoration: none; }
        .btn-wpp { background: #00C853; color: #fff; } .btn-laudo { background: #0F172A; color: #fff; } .btn-google { background: #EFF6FF; color: #1D4ED8; }
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
        <div class="stat-card"><small>Total</small><strong>{{ stats.total }}</strong></div>
        <div class="stat-card"><small>Completos</small><strong style="color:#00A645;">{{ stats.completos }}</strong></div>
        <div class="stat-card"><small>Incompletos</small><strong style="color:#D97706;">{{ stats.incompletos }}</strong></div>
        <div class="stat-card"><small>Cliques no CTA 🔥</small><strong style="color:#DC2626;">{{ stats.cliques_cta }}</strong></div>
        <div class="stat-card"><small>Reuniões</small><strong style="color:#2563EB;">{{ stats.reunioes }}</strong></div>
    </div>
    <div class="filters">
        <button class="filter-btn active" onclick="filtrar('TODOS', this)">Todos</button>
        <button class="filter-btn" onclick="filtrar('Lead Incompleto', this)">Incompletos</button>
        <button class="filter-btn" onclick="filtrar('Reunião Agendada', this)">Reunião Agendada</button>
        <input type="text" class="search-inp" id="busca" placeholder="Buscar..." onkeyup="buscarTexto()">
    </div>
    <div class="lead-grid">
        {% for l in leads %}
        <div class="lead-card {% if not l.completo %}incompleto{% elif l.clicou_cta %}quente{% endif %}" data-status="{{ l.status_crm }}" data-search="{{ (l.empresa ~ ' ' ~ l.cnpj) | lower }}">
            <div>
                <div class="badges">
                    {% if l.completo %}<span class="badge b-comp">✅ Completo</span>{% else %}<span class="badge b-inc">⏳ Incompleto</span>{% endif %}
                    {% if l.clicou_cta %}<span class="badge b-hot">🔥 Clicou CTA</span>{% endif %}
                </div>
                <div class="lead-title">{{ l.empresa }}</div>
                <div class="lead-meta">CNPJ: {{ l.cnpj | cnpj_fmt }}<br>👤 {{ l.solicitante or 'Aguardando' }} • 📱 {{ l.whatsapp or '-' }}</div>
                {% if l.completo %}
                <div class="lead-nums">Fat: {{ l.faturamento | moeda }} | Pontos Cegos: <strong>{{ l.qtd_cegas }}</strong> | Potencial: <strong style="color:#00A645;">{{ l.potencial_oculto | moeda }}</strong></div>
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
                    {% if l.link_wpp_abordagem %}
                        <a href="{{ l.link_wpp_abordagem }}" target="_blank" class="btn-act btn-wpp">💬 Abordar</a>
                        <a href="/laudo/{{ l.cnpj }}" target="_blank" class="btn-act btn-laudo">📄 Laudo</a>
                    {% else %}
                        <a href="https://www.google.com/search?q={{ l.empresa | urlencode }}" target="_blank" class="btn-act btn-google">🔍 Google</a>
                    {% endif %}
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
<script>
    function filtrar(st, btn) {
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active')); btn.classList.add('active');
        document.querySelectorAll('.lead-card').forEach(c => c.style.display = (st === 'TODOS' || c.getAttribute('data-status') === st) ? 'flex' : 'none');
    }
    function buscarTexto() {
        let t = document.getElementById('busca').value.toLowerCase();
        document.querySelectorAll('.lead-card').forEach(c => c.style.display = c.getAttribute('data-search').includes(t) ? 'flex' : 'none');
    }
    async function atualizarStatus(cnpj, sel) {
        await fetch('/api/lead-status', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cnpj: cnpj, status: sel.value})});
        let ok = document.getElementById(`ok-${cnpj}`); ok.style.opacity = '1'; setTimeout(() => ok.style.opacity = '0', 1500);
    }
</script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)