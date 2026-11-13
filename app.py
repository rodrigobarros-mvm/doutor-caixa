from flask import Flask, render_template_string, request, send_file
import io
import math
from fpdf import FPDF
from supabase import create_client, Client

app = Flask(__name__)

# --- CONFIGURAÇÃO DO SUPABASE ---
SUPABASE_URL = "https://zkhjvkajtjhqlxkzxpx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpraGp2a2FqdGp0aHFseGt6eHB4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ0OTk0MjAsImV4cCI6MjExMDA3NTQyMH0.i3K8SXNNPHamqLobcdK-yJ1YyGgS7-qqRpfjLnJPqE4"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def buscar_cliente_db(cnpj_bruto):
    cnpj_limpo = "".join(filter(str.isdigit, str(cnpj_bruto)))
    
    # 1. Busca na nuvem (Supabase)
    try:
        response = supabase.table("clientes_doutor_caixa").select("*").eq("cnpj", cnpj_limpo).execute()
        dados = response.data
        if dados and len(dados) > 0:
            row = dados[0]
            return {
                "nome": row["nome"],
                "ativo": row["ativo"],
                "caixa": float(row["caixa"]),
                "fat": float(row["fat"]),
                "fixo": float(row["fixo"]),
                "margem": float(row["margem"])
            }
    except Exception as e:
        print(f"Aviso: Nuvem indisponível ({e}). Usando base de contingência local...")
    
    # 2. Fallback de segurança
    BASE_LOCAL_SEGURANCA = {
        "11222333000181": {"nome": "Comércio Exemplo RMR Ltda", "ativo": True, "caixa": 120000.00, "fat": 300000.00, "fixo": 95000.00, "margem": 38.0},
        "44555666000199": {"nome": "Inadimplente Teste S/A", "ativo": False, "caixa": 50000.00, "fat": 100000.00, "fixo": 40000.00, "margem": 30.0}
    }
    return BASE_LOCAL_SEGURANCA.get(cnpj_limpo, None)

def format_brl(value):
    return "{:,.2f}".format(value).replace(",", "X").replace(".", ",").replace("X", ".")

def format_cnpj(cnpj):
    c = "".join(filter(str.isdigit, str(cnpj)))
    if len(c) == 14:
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"
    return c

app.jinja_env.filters['format_brl'] = format_brl
app.jinja_env.filters['format_cnpj'] = format_cnpj

# --- TEMPLATES HTML ---
TEMPLATE_DASHBOARD = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa | Laudo Financeiro</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --verde-caixa: #00C853;
            --verde-profundo: #0F2E1C;
            --menta-suave: #E8F7EE;
            --branco: #FFFFFF;
            --cinza-neutro: #6B7A70;
            --cor-alerta-texto: #c0392b;
            --cor-alerta-fundo: #fdeed9;
            --whatsapp: #25D366;
            --azul-metrica: #2980b9;
            --azul-fundo: #ebf5fb;
        }
        * { box-sizing: border-box; }
        body {
            font-family: 'Poppins', sans-serif;
            background: var(--menta-suave);
            margin: 0;
            padding: 24px 16px;
            color: var(--verde-profundo);
            -webkit-font-smoothing: antialiased;
        }
        .container {
            max-width: 820px;
            margin: 0 auto;
            background: var(--branco);
            padding: 36px;
            border-radius: 14px;
            box-shadow: 0 6px 20px rgba(15, 46, 28, 0.06);
        }
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 2px solid var(--menta-suave);
            padding-bottom: 18px;
            margin-bottom: 24px;
            gap: 16px;
        }
        .logo { max-width: 150px; height: auto; }
        .header-titles { text-align: right; }
        .header h1 { color: var(--verde-profundo); font-size: 24px; margin: 0; font-weight: 700; line-height: 1.2; }
        .header span { font-size: 12px; color: var(--cinza-neutro); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }

        .paciente-box {
            background: #f7faf8;
            padding: 14px 18px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 5px solid var(--verde-profundo);
        }
        .paciente-box p { margin: 0; font-size: 16px; color: var(--cinza-neutro); }
        .paciente-box strong { color: var(--verde-profundo); }
        .paciente-box small { display: block; margin-top: 2px; font-size: 13px; color: var(--cinza-neutro); }

        .card {
            background: var(--menta-suave);
            padding: 18px 20px;
            border-radius: 10px;
            margin-bottom: 14px;
            border-left: 5px solid var(--verde-caixa);
        }
        .card-label { color: var(--cinza-neutro); font-weight: 700; font-size: 14px; }
        .alert-red { border-left-color: var(--cor-alerta-texto); background: var(--cor-alerta-fundo); }
        .alert-green { border-left-color: var(--verde-caixa); background: var(--menta-suave); }
        .alert-blue { border-left-color: var(--azul-metrica); background: var(--azul-fundo); }

        .value { font-size: 26px; font-weight: 700; color: var(--verde-profundo); margin-top: 4px; }
        .value.red { color: var(--cor-alerta-texto); }
        .value.blue { color: var(--azul-metrica); }
        .helper-text { font-size: 12px; color: var(--cinza-neutro); margin-top: 4px; }

        .prescricao-card {
            background: var(--verde-profundo);
            border-left: 5px solid var(--verde-caixa);
            color: var(--branco);
            padding: 22px 20px;
            border-radius: 10px;
            margin-bottom: 16px;
        }
        .prescricao-title { color: var(--verde-caixa); font-size: 16px; font-weight: 700; margin-bottom: 14px; letter-spacing: 0.3px; }
        .lista-acoes p { margin: 0 0 12px 0; color: #f0f4f1; font-size: 15px; line-height: 1.5; }
        .lista-acoes p:last-child { margin-bottom: 0; }
        .lista-acoes strong { color: var(--branco); font-weight: 700; }

        /* BLOCO EM DESTAQUE: MÉTRICAS CEGAS */
        .metricas-cegas-card {
            background: #fff5f5;
            border: 2px solid #e74c3c;
            border-left: 6px solid #c0392b;
            border-radius: 10px;
            padding: 22px 20px;
            margin: 18px 0;
        }
        .mc-badge {
            display: inline-block;
            background: #c0392b;
            color: #ffffff;
            font-size: 11px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 4px;
            letter-spacing: 0.6px;
            text-transform: uppercase;
            margin-bottom: 8px;
        }
        .mc-title {
            color: #922b21;
            font-size: 18px;
            font-weight: 700;
            margin: 0 0 8px 0;
        }
        .mc-intro {
            color: #333333;
            font-size: 14px;
            margin: 0 0 14px 0;
            line-height: 1.5;
        }
        .mc-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-bottom: 14px;
        }
        .mc-item {
            background: #ffffff;
            border: 1px solid #f5b7b1;
            border-left: 4px solid #c0392b;
            border-radius: 6px;
            padding: 10px 12px;
        }
        .mc-item strong {
            display: block;
            color: #c0392b;
            font-size: 13px;
            margin-bottom: 3px;
        }
        .mc-item span {
            display: block;
            color: #4a4a4a;
            font-size: 12.5px;
            line-height: 1.4;
        }
        .mc-footer {
            margin: 0;
            font-size: 13.5px;
            font-weight: 700;
            color: #922b21;
        }

        .consequencia {
            background: #fdeed9;
            border-left: 5px solid #d35400;
            padding: 16px 18px;
            margin-bottom: 20px;
            border-radius: 10px;
        }
        .consequencia h4 { color: #a04000; margin: 0 0 6px 0; font-size: 15px; font-weight: 700; }
        .consequencia p { color: #333333; margin: 0; font-size: 14px; line-height: 1.5; }

        .botoes { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 24px; }
        .btn {
            background: var(--verde-caixa);
            color: var(--branco);
            padding: 15px 18px;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 700;
            text-align: center;
            flex: 1;
            min-width: 200px;
            transition: background 0.2s;
            font-size: 15px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .btn:hover { background: #00a645; }
        .btn-outline { background: transparent; border: 2px solid var(--verde-profundo); color: var(--verde-profundo); }
        .btn-outline:hover { background: var(--verde-profundo); color: var(--branco); }
        .btn-wpp { background: var(--whatsapp); color: #ffffff; }
        .btn-wpp:hover { background: #1ebe57; }

        /* RESPONSIVIDADE SMARTPHONE (FLAT & HARMÔNICO) */
        @media (max-width: 640px) {
            body {
                padding: 0;
                background: var(--branco);
            }
            .container {
                max-width: 100%;
                border-radius: 0;
                box-shadow: none;
                padding: 20px 16px 32px 16px;
            }
            .header {
                flex-direction: row;
                align-items: center;
                padding-bottom: 14px;
                margin-bottom: 18px;
            }
            .logo { max-width: 110px; }
            .header h1 { font-size: 18px; }
            .header span { font-size: 10px; }
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
                <span>Diagnóstico Executivo</span>
                <h1>Laudo de Resiliência</h1>
            </div>
        </div>
        
        <div class="paciente-box">
            <p>Paciente (Empresa): <strong>{{ cliente.nome }}</strong></p>
            <small>CNPJ: {{ cnpj|format_cnpj }}</small>
        </div>
        
        <div class="card alert-blue">
            <div class="card-label">Ponto de Equilíbrio (Faturamento Mínimo Mensal)</div>
            <div class="value blue">R$ {{ ponto_equilibrio|format_brl }}</div>
            <div class="helper-text">*Faturamento necessário para cobrir todos os custos e não ter prejuízo.</div>
        </div>
        
        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div class="card-label">Faturamento Projetado (Pior Cenário -30%)</div>
            <div class="value">R$ {{ fat_estresse|format_brl }}</div>
        </div>

        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div class="card-label">Lucro Líquido Projetado (Cenário de Estresse)</div>
            <div class="value {% if lucro < 0 %}red{% endif %}">R$ {{ lucro|format_brl }}</div>
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

        <div class="metricas-cegas-card">
            <span class="mc-badge">🚨 Risco Oculto Detectado</span>
            <h3 class="mc-title">ALERTA CRÍTICO: MÉTRICAS CEGAS NA OPERAÇÃO</h3>
            <p class="mc-intro">O nosso pré-diagnóstico aponta que a sua empresa opera sem visibilidade exata sobre 4 indicadores vitais de escala e margem:</p>
            <div class="mc-grid">
                <div class="mc-item">
                    <strong>1. CAC (Custo de Aquisição)</strong>
                    <span>Você não sabe quanto custa colocar cada novo cliente para dentro da empresa.</span>
                </div>
                <div class="mc-item">
                    <strong>2. LTV (Lifetime Value)</strong>
                    <span>Desconhece o lucro real que cada cliente deixa ao longo do relacionamento.</span>
                </div>
                <div class="mc-item">
                    <strong>3. Taxa de Conversão</strong>
                    <span>Falta rastreabilidade do funil comercial entre prospecção e fechamento.</span>
                </div>
                <div class="mc-item">
                    <strong>4. Ciclo Financeiro (Prazos)</strong>
                    <span>Risco de descasamento entre prazo de recebimento e pagamento corroer o caixa.</span>
                </div>
            </div>
            <p class="mc-footer">Pilotar sem esses números significa queimar margem todos os dias no escuro.</p>
        </div>
        
        {% if lucro < 0 %}
        <div class="consequencia">
            <h4>⚠️ CONSEQUÊNCIA DA INAÇÃO</h4>
            <p>Se as medidas acima não forem aplicadas imediatamente, o capital de giro da empresa será consumido em <strong>{{ "%.1f"|format(meses_runway) }} meses</strong>, resultando em paralisação operacional ou captação de crédito a juros predatórios.</p>
        </div>
        {% endif %}

        <div class="botoes">
            <a href="https://wa.me/5581979091165?text=Olá,%20acabei%20de%20gerar%20meu%20laudo%20financeiro%20no%20Doutor%20Caixa%20e%20preciso%20de%20ajuda%20estratégica%20urgente." target="_blank" class="btn btn-wpp">💬 Falar com Especialista Agora</a>
            <a href="/baixar_pdf/{{ cnpj }}" class="btn">📄 Baixar Laudo PDF</a>
            <a href="/" class="btn btn-outline">Consultar Outro CNPJ</a>
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_HOME = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Doutor Caixa | Acesso</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: 'Poppins', sans-serif;
            background: #E8F7EE;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            padding: 16px;
        }
        .login-box {
            background: #FFFFFF;
            padding: 40px 32px;
            border-radius: 14px;
            box-shadow: 0 6px 20px rgba(15, 46, 28, 0.06);
            text-align: center;
            max-width: 420px;
            width: 100%;
        }
        .logo { max-width: 140px; margin-bottom: 18px; }
        h2 { color: #0F2E1C; margin: 0 0 8px 0; font-size: 22px; }
        p { color: #6B7A70; font-size: 14px; margin: 0 0 20px 0; }
        input {
            width: 100%;
            padding: 15px;
            margin-bottom: 16px;
            border: 2px solid #E8F7EE;
            border-radius: 8px;
            font-family: 'Poppins', sans-serif;
            font-size: 16px;
            outline: none;
        }
        input:focus { border-color: #00C853; }
        button {
            background: #00C853;
            color: white;
            padding: 16px;
            width: 100%;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 700;
            font-family: 'Poppins', sans-serif;
            font-size: 16px;
        }
        button:hover { background: #00a645; }
        @media (max-width: 480px) {
            body { background: #FFFFFF; padding: 0; align-items: flex-start; }
            .login-box { box-shadow: none; border-radius: 0; padding: 48px 20px; max-width: 100%; }
        }
    </style>
</head>
<body>
    <div class="login-box">
        <img src="/static/logo.png" alt="Doutor Caixa Logo" class="logo">
        <h2>Doutor Caixa | Acesso</h2>
        <p>Digite seu CNPJ para acessar o laudo financeiro.</p>
        <form method="POST" action="/acessar">
            <input type="text" name="cnpj" inputmode="numeric" placeholder="Somente números" required>
            <button type="submit">Acessar Laudo</button>
        </form>
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
        <p style="color: #6B7A70; font-size: 14px;">Sua assinatura do Doutor Caixa encontra-se pendente.</p>
        <a href="https://wa.me/5581979091165?text=Olá,%20meu%20acesso%20ao%20Doutor%20Caixa%20está%20bloqueado.%20Poderia%20ajudar?" target="_blank" class="btn-wpp">💬 Falar com Suporte (WhatsApp)</a>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(TEMPLATE_HOME)

@app.route('/acessar', methods=['POST'])
def acessar():
    cnpj_input = request.form.get('cnpj', '')
    cnpj_limpo = "".join(filter(str.isdigit, cnpj_input))
    
    cliente = buscar_cliente_db(cnpj_limpo)
    
    if not cliente:
        return "CNPJ não encontrado na base de dados do Doutor Caixa."
        
    if not cliente['ativo']:
        return render_template_string(TEMPLATE_BLOQUEIO)
    
    fat_estresse = cliente['fat'] * 0.70
    lucro = (fat_estresse * (cliente['margem'] / 100)) - cliente['fixo']
    meses_runway = cliente['caixa'] / abs(lucro) if lucro < 0 else 0
    ponto_equilibrio = cliente['fixo'] / (cliente['margem'] / 100)
    
    if lucro < 0:
        acao = [
            "<strong>1. REESTRUTURAÇÃO IMEDIATA:</strong> Reduzir custos fixos não essenciais em pelo menos 15%.",
            "<strong>2. INTELIGÊNCIA COMERCIAL:</strong> Aumentar o volume de prospecção (Meta urgente: 30 contatos/dia) para reverter a queda.",
            "<strong>3. PROTEÇÃO DE CAPITAL:</strong> Congelar antecipações de recebíveis e renegociar prazos com fornecedores."
        ]
    else:
        acao = [
            "<strong>1. EXPANSÃO ESTRATÉGICA:</strong> Utilizar a resiliência do caixa para campanhas de aquisição de novos clientes.",
            "<strong>2. BLINDAGEM DE MARGEM:</strong> Revisar a precificação para potencializar o lucro líquido.",
            "<strong>3. ESCALA DE VENDAS:</strong> Subir a régua de contatos diários focando em alto ticket."
        ]
    
    return render_template_string(TEMPLATE_DASHBOARD, cliente=cliente, cnpj=cnpj_limpo, fat_estresse=fat_estresse, lucro=lucro, meses_runway=meses_runway, acao=acao, ponto_equilibrio=ponto_equilibrio)

@app.route('/baixar_pdf/<cnpj>')
def baixar_pdf(cnpj):
    cliente = buscar_cliente_db(cnpj)
    if not cliente:
        return "Erro", 404
    
    fat_estresse = cliente['fat'] * 0.70
    lucro = (fat_estresse * (cliente['margem'] / 100)) - cliente['fixo']
    ponto_equilibrio = cliente['fixo'] / (cliente['margem'] / 100)
    is_critical = lucro < 0
    
    class PDF(FPDF):
        def header(self):
            try:
                self.image('static/logo.png', 12, 9, 30)
            except:
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

    # --- BLOCO 1: PACIENTE ---
    y = pdf.get_y()
    desenhar_card(y, 19, (247, 250, 248), (15, 46, 28))
    pdf.set_xy(19, y + 3.5)
    pdf.set_font('helvetica', 'B', 11)
    pdf.set_text_color(15, 46, 28)
    pdf.cell(175, 6, f"PACIENTE (EMPRESA): {cliente['nome']}", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 9.5)
    pdf.set_text_color(107, 122, 112)
    pdf.cell(175, 5.5, f"CNPJ: {format_cnpj(cnpj)}", ln=1)
    pdf.set_y(y + 19 + 7)

    # --- BLOCO 2: PONTO DE EQUILÍBRIO ---
    y = pdf.get_y()
    desenhar_card(y, 25, (235, 245, 251), (41, 128, 185))
    pdf.set_xy(19, y + 3.5)
    pdf.set_font('helvetica', 'B', 9)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 5, "PONTO DE EQUILÍBRIO (FATURAMENTO MÍNIMO MENSAL)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 17)
    pdf.set_text_color(41, 128, 185)
    pdf.cell(175, 8, f"R$ {format_brl(ponto_equilibrio)}", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 8)
    pdf.set_text_color(107, 122, 112)
    pdf.cell(175, 4.5, "Faturamento mínimo necessário para cobrir custos fixos e variáveis sem prejuízo.", ln=1)
    pdf.set_y(y + 25 + 7)

    # --- BLOCO 3: DIAGNÓSTICO DE ESTRESSE ---
    y = pdf.get_y()
    bg_color = (253, 237, 236) if is_critical else (232, 247, 238)
    bar_color = (192, 57, 43) if is_critical else (0, 200, 83)
    val_color = (192, 57, 43) if is_critical else (15, 46, 28)
    status_text = "PREJUÍZO / QUEIMA DE CAIXA" if is_critical else "CAIXA BLINDADO"

    desenhar_card(y, 28, bg_color, bar_color)
    pdf.set_xy(19, y + 3.5)
    pdf.set_font('helvetica', 'B', 9)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 5, "DIAGNÓSTICO DE ESTRESSE (CENÁRIO DE QUEDA DE 30% NO FATURAMENTO)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 9.5)
    pdf.set_text_color(50, 50, 50)
    pdf.cell(175, 5.5, f"Faturamento Projetado: R$ {format_brl(fat_estresse)}   |   Lucro Líquido Projetado:", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', 'B', 15)
    pdf.set_text_color(*val_color)
    pdf.cell(175, 8.5, f"R$ {format_brl(lucro)}   ({status_text})", ln=1)
    pdf.set_y(y + 28 + 7)

    # --- BLOCO 4: FÔLEGO FINANCEIRO (RUNWAY) ---
    y = pdf.get_y()
    desenhar_card(y, 22, bg_color, bar_color)
    pdf.set_xy(19, y + 3.5)
    pdf.set_font('helvetica', 'B', 9)
    pdf.set_text_color(93, 109, 126)
    pdf.cell(175, 5, "FÔLEGO FINANCEIRO (RUNWAY DE CAIXA)", ln=1)
    pdf.set_x(19)
    pdf.set_font('helvetica', '', 9.5)
    pdf.set_text_color(40, 40, 40)
    if is_critical:
        runway = cliente['caixa'] / abs(lucro)
        texto_runway = f"ALERTA: O caixa atual (R$ {format_brl(cliente['caixa'])}) suporta apenas {runway:.1f} meses operando neste cenário de estresse."
    else:
        texto_runway = f"ESTÁVEL: A empresa possui margem suficiente para absorver a queda sem queimar o caixa (R$ {format_brl(cliente['caixa'])})."
    pdf.multi_cell(175, 5, texto_runway)
    pdf.set_y(y + 22 + 7)

    # --- BLOCO 5: PRESCRIÇÃO ESTRATÉGICA ---
    itens_prescricao = [
        ("1. REESTRUTURAÇÃO IMEDIATA: ", "Reduzir custos fixos não essenciais em pelo menos 15%."),
        ("2. INTELIGÊNCIA COMERCIAL: ", "Aumentar o volume de prospecção (Meta: 30 contatos/dia) para reverter a queda."),
        ("3. PROTEÇÃO DE CAPITAL: ", "Congelar antecipações de recebíveis e renegociar prazos com fornecedores.")
    ] if is_critical else [
        ("1. EXPANSÃO ESTRATÉGICA: ", "Utilizar a resiliência do caixa para campanhas de aquisição de novos clientes."),
        ("2. BLINDAGEM DE MARGEM: ", "Revisar a precificação para potencializar o lucro líquido."),
        ("3. ESCALA DE VENDAS: ", "Subir a régua de contatos diários (Meta: 30/dia) focando em alto ticket.")
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
        pdf.write(5.2, tit)
        pdf.set_font('helvetica', '', 9.5)
        pdf.write(5.2, desc + "\n")
        pdf.ln(2.2)

    pdf.set_left_margin(12)
    pdf.set_right_margin(12)

    # --- PÁGINA 2: MÉTRICAS CEGAS EM DESTAQUE + CTA WHATSAPP ---
    pdf.add_page()
    y = pdf.get_y()

    pontos_cegos = [
        ("1. CAC (Custo de Aquisição de Clientes): ", "Você não sabe quanto custa colocar cada novo cliente para dentro da empresa."),
        ("2. LTV (Lifetime Value): ", "Desconhece o lucro real que cada cliente deixa ao longo de todo o relacionamento."),
        ("3. Taxa de Conversão e Funil Comercial: ", "Falta rastreabilidade exata entre prospecção, propostas enviadas e fechamento."),
        ("4. Ciclo Financeiro (Prazos): ", "Risco oculto de descasamento entre prazos de recebimento e pagamento corroer o caixa.")
    ]

    altura_card_cegas = 96
    pdf.set_fill_color(255, 245, 245)
    pdf.set_draw_color(220, 76, 62)
    pdf.set_line_width(0.5)
    pdf.rect(12, y, 186, altura_card_cegas, 'DF')
    pdf.set_fill_color(192, 57, 43)
    pdf.rect(12, y, 3.5, altura_card_cegas, 'F')

    pdf.set_xy(20, y + 5)
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(192, 57, 43)
    pdf.cell(172, 6.5, "ALERTA CRÍTICO: MÉTRICAS CEGAS DETECTADAS NA OPERAÇÃO", ln=1)

    pdf.set_x(20)
    pdf.set_font('helvetica', '', 9.5)
    pdf.set_text_color(50, 50, 50)
    pdf.multi_cell(172, 5, "O nosso pré-diagnóstico aponta que a sua operação pilota no escuro em 4 indicadores vitais:")
    pdf.ln(3)

    for tit, desc in pontos_cegos:
        y_item = pdf.get_y()
        pdf.set_fill_color(255, 255, 255)
        pdf.set_draw_color(245, 183, 177)
        pdf.set_line_width(0.3)
        pdf.rect(20, y_item, 172, 13.5, 'DF')
        pdf.set_fill_color(192, 57, 43)
        pdf.rect(20, y_item, 2, 13.5, 'F')

        pdf.set_xy(24, y_item + 2)
        pdf.set_font('helvetica', 'B', 9.5)
        pdf.set_text_color(192, 57, 43)
        pdf.cell(165, 4.5, tit.strip(), ln=1)

        pdf.set_x(24)
        pdf.set_font('helvetica', '', 8.8)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(165, 4.5, desc, ln=1)

        pdf.set_y(y_item + 15.5)

    pdf.set_x(20)
    pdf.set_font('helvetica', 'B', 9.5)
    pdf.set_text_color(146, 43, 33)
    pdf.cell(172, 6, "Operar sem esses números significa queimar margem todos os dias sem perceber.", ln=1)

    pdf.set_y(y + altura_card_cegas + 9)

    # --- CONSEQUÊNCIA DA INAÇÃO (SE CRÍTICO) ---
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
        runway = cliente['caixa'] / abs(lucro)
        pdf.multi_cell(175, 4.8, f"Se as medidas acima não forem aplicadas imediatamente, o capital de giro será consumido em {runway:.1f} meses, exigindo captação de crédito a juros predatórios.")
        pdf.set_y(y_cons + 24 + 10)

    # --- CTA WHATSAPP ---
    y_btn = pdf.get_y()
    pdf.set_fill_color(37, 211, 102)
    pdf.set_font('helvetica', 'B', 11.5)
    pdf.set_text_color(255, 255, 255)
    link_wpp = "https://wa.me/5581979091165?text=Olá,%20acabei%20de%20gerar%20meu%20laudo%20no%20Doutor%20Caixa%20e%20preciso%20de%20ajuda%20estratégica."
    pdf.set_xy(45, y_btn)
    pdf.cell(120, 13, "FALAR COM O DOUTOR CAIXA NO WHATSAPP", fill=True, align='C', link=link_wpp)

    pdf_bytes = bytearray(pdf.output())
    return send_file(io.BytesIO(pdf_bytes), download_name=f"Laudo_Doutor_Caixa_{cnpj}.pdf", as_attachment=True, mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True, port=5000)