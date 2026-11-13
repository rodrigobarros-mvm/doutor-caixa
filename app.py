from flask import Flask, render_template_string, request, send_file
import io
from fpdf import FPDF
from supabase import create_client, Client

app = Flask(__name__)

# --- CONFIGURAÇÃO DO SUPABASE ---
SUPABASE_URL = "https://zkhjvkajtjhqlxkzxpx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpraGp2a2FqdGpocWx4a3pweCIsInJvbGUiOiJhbm9uIiwiaWF0IjoxNzMxMjY2NDgwLCJleHAiOjIwNDY4MjY0ODB9.eyJtQmlhcyI6IjFIMjAzQmh2bVZzISinIzlzaW1fub24pZSIzSjZImFub3I0c0l0QjRzISJ9..."

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def buscar_cliente_db(cnpj_bruto):
    cnpj_limpo = "".join(filter(str.isdigit, str(cnpj_bruto)))
    
    # 1. Tenta buscar no Supabase (Nuvem)
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
    
    # 2. Fallback de Segurança (Caso a internet/Supabase bloqueie)
    BASE_LOCAL_SEGURANCA = {
        "11222333000181": {"nome": "Comércio Exemplo RMR Ltda", "ativo": True, "caixa": 120000.00, "fat": 300000.00, "fixo": 95000.00, "margem": 38.0},
        "44555666000199": {"nome": "Inadimplente Teste S/A", "ativo": False, "caixa": 50000.00, "fat": 100000.00, "fixo": 40000.00, "margem": 30.0}
    }
    
    return BASE_LOCAL_SEGURANCA.get(cnpj_limpo, None)

def format_brl(value):
    return "{:,.2f}".format(value).replace(",", "X").replace(".", ",").replace("X", ".")

app.jinja_env.filters['format_brl'] = format_brl

# --- TEMPLATES HTML ---
TEMPLATE_DASHBOARD = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <title>Doutor Caixa | Laudo Financeiro</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;700&display=swap" rel="stylesheet">
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
            --azul-metrica: #3498db;
            --azul-fundo: #ebf5fb;
        }
        body { font-family: 'Poppins', sans-serif; background: var(--menta-suave); margin: 0; padding: 20px; color: var(--verde-profundo); }
        .container { max-width: 800px; margin: 0 auto; background: var(--branco); padding: 40px; border-radius: 12px; box-shadow: 0 8px 24px rgba(15, 46, 28, 0.08); }
        
        .header { display: flex; align-items: center; border-bottom: 2px solid var(--menta-suave); padding-bottom: 20px; margin-bottom: 30px; }
        .logo { max-width: 180px; margin-right: 25px; }
        .header h1 { color: var(--verde-profundo); font-size: 26px; margin: 0; font-weight: 700; }
        
        p { color: var(--cinza-neutro); font-size: 19px; }
        strong { color: var(--verde-profundo); }
        
        .card { background: var(--menta-suave); padding: 20px; border-radius: 8px; margin-bottom: 15px; border-left: 6px solid var(--verde-caixa); }
        .alert-red { border-left-color: var(--cor-alerta-texto); background: var(--cor-alerta-fundo); }
        .alert-green { border-left-color: var(--verde-caixa); background: var(--menta-suave); }
        .alert-blue { border-left-color: var(--azul-metrica); background: var(--azul-fundo); }
        
        .value { font-size: 26px; font-weight: 700; color: var(--verde-profundo); margin-top: 5px; }
        .value.red { color: var(--cor-alerta-texto); }
        .value.blue { color: var(--azul-metrica); }
        
        .consequencia { background: #fff0f0; border-left: 6px solid #c0392b; padding: 15px; margin-top: 15px; border-radius: 8px; }
        .consequencia h4 { color: #c0392b; margin: 0 0 5px 0; font-size: 18px; }
        .consequencia p { color: #333; margin: 0; font-size: 16px; font-weight: 500; }
        
        .botoes { display: flex; flex-wrap: wrap; gap: 15px; margin-top: 30px; }
        .btn { background: var(--verde-caixa); color: var(--branco); padding: 15px 20px; text-decoration: none; border-radius: 6px; font-weight: 700; text-align: center; flex: 1; min-width: 200px; transition: all 0.3s; font-size: 16px; }
        .btn:hover { background: #00a645; }
        .btn-outline { background: transparent; border: 2px solid var(--verde-profundo); color: var(--verde-profundo); }
        .btn-outline:hover { background: var(--verde-profundo); color: var(--branco); }
        
        .btn-wpp { background: var(--whatsapp); color: white; display: flex; align-items: center; justify-content: center; animation: pulse 2s infinite; }
        .btn-wpp:hover { background: #1ebe57; }
        @keyframes pulse { 0% { transform: scale(1); } 50% { transform: scale(1.03); } 100% { transform: scale(1); } }
        
        .lista-acoes p { margin-bottom: 20px; color: var(--branco); font-size: 16px; }
        .lista-acoes p:last-child { margin-bottom: 0; }
        .lista-acoes strong { color: var(--branco); font-weight: 700; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <img src="/static/logo.png" alt="Doutor Caixa Logo" class="logo">
            <h1>Laudo de Resiliência</h1>
        </div>
        
        <p>Paciente (Empresa): <strong style="color: var(--verde-profundo);">{{ cliente.nome }}</strong> <br><small>CNPJ: {{ cnpj }}</small></p>
        
        <div class="card alert-blue">
            <div style="color: var(--cinza-neutro); font-weight: 700;">Ponto de Equilíbrio (Faturamento Mínimo Mensal):</div>
            <div class="value blue">R$ {{ ponto_equilibrio|format_brl }}</div>
            <div style="font-size: 12px; color: var(--cinza-neutro); margin-top: 5px;">*Faturamento necessário para cobrir todos os custos e não ter prejuízo.</div>
        </div>
        
        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div style="color: var(--cinza-neutro); font-weight: 700;">Faturamento Projetado (Pior Cenário - 30%):</div>
            <div class="value">R$ {{ fat_estresse|format_brl }}</div>
        </div>

        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div style="color: var(--cinza-neutro); font-weight: 700;">Lucro Líquido Projetado (Cenário de Estresse):</div>
            <div class="value {% if lucro < 0 %}red{% endif %}">R$ {{ lucro|format_brl }}</div>
        </div>

        <div class="card {% if lucro < 0 %}alert-red{% else %}alert-green{% endif %}">
            <div style="color: var(--cinza-neutro); font-weight: 700;">Status Clínico do Caixa (Runway):</div>
            <div class="value {% if lucro < 0 %}red{% endif %}" style="font-size: 20px;">
                {% if lucro < 0 %}
                    🔴 CRÍTICO: Hemorragia de caixa. Fôlego para {{ "%.1f"|format(meses_runway) }} meses. 
                {% else %}
                    🟢 ESTÁVEL: Caixa blindado e margem segura na crise.
                {% endif %}
            </div>
        </div>

        <div class="card" style="background: var(--verde-profundo); border: none; color: white;">
            <div style="color: var(--verde-caixa); font-size: 18px; margin-bottom: 15px;"><strong>PRESCRIÇÃO ESTRATÉGICA (O QUE FAZER AGORA?)</strong></div>
            <div class="lista-acoes">
                {% for item in acao %}
                    <p>{{ item|safe }}</p>
                {% endfor %}
            </div>
        </div>
        
        {% if lucro < 0 %}
        <div class="consequencia">
            <h4>⚠️ CONSEQUÊNCIA DA INAÇÃO</h4>
            <p>Se as medidas acima não forem aplicadas imediatamente, o capital de giro da empresa será consumido em {{ "%.1f"|format(meses_runway) }} meses, resultando em paralisação operacional ou necessidade de captação de crédito a juros predatórios.</p>
        </div>
        {% endif %}

        <div class="botoes">
            <a href="/baixar_pdf/{{ cnpj }}" class="btn">📄 Baixar Laudo PDF</a>
            <a href="https://wa.me/5581979091165?text=Olá,%20acabei%20de%20gerar%20meu%20laudo%20financeiro%20no%20Doutor%20Caixa%20e%20preciso%20de%20ajuda%20estratégica%20urgente." target="_blank" class="btn btn-wpp">💬 Falar com Especialista Agora</a>
            <a href="/" class="btn btn-outline">Consultar Outro</a>
        </div>
    </div>
</body>
</html>
"""

TEMPLATE_HOME = """
<html lang="pt-BR">
<head>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;700&display=swap" rel="stylesheet">
</head>
<body style="font-family: 'Poppins', sans-serif; background: #E8F7EE; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0;">
<div style="background: #FFFFFF; padding: 50px; border-radius: 12px; box-shadow: 0 8px 24px rgba(15, 46, 28, 0.08); text-align: center; max-width: 400px; width: 100%;">
    <img src="/static/logo.png" alt="Doutor Caixa Logo" class="logo" style="max-width: 150px; margin-bottom: 20px;">
    <h2 style="color: #0F2E1C; margin-top: 0;">Doutor Caixa | Acesso</h2>
    <p style="color: #6B7A70; font-size: 14px;">Digite seu CNPJ para acessar o laudo financeiro.</p>
    <form method="POST" action="/acessar">
        <input type="text" name="cnpj" placeholder="Somente números" style="width: 100%; padding: 15px; margin: 20px 0; border: 2px solid #E8F7EE; border-radius: 6px; box-sizing: border-box; font-family: 'Poppins'; font-size: 16px;" required>
        <button type="submit" style="background: #00C853; color: white; padding: 15px; width: 100%; border: none; border-radius: 6px; cursor: pointer; font-weight: 700; font-family: 'Poppins'; font-size: 16px;">Acessar Laudo</button>
    </form>
</div></body></html>
"""

TEMPLATE_BLOQUEIO = """
<html lang="pt-BR">
<head>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;700&display=swap" rel="stylesheet">
    <style>
        .btn-wpp { background: #25D366; color: white; padding: 15px; width: 100%; border-radius: 6px; text-decoration: none; font-weight: 700; display: inline-block; margin-top: 20px; box-sizing: border-box; }
        .btn-wpp:hover { background: #1ebe57; }
    </style>
</head>
<body style="font-family: 'Poppins', sans-serif; background: #fdeed9; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0;">
    <div style="text-align: center; background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); max-width: 400px; width: 100%;">
        <img src="/static/logo.png" alt="Doutor Caixa Logo" class="logo" style="max-width: 150px; margin-bottom: 20px;">
        <h2 style="color:#c0392b; margin-top: 0;">Acesso Bloqueado</h2>
        <p style="color: #6B7A70;">Sua assinatura do Doutor Caixa encontra-se pendente.</p>
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
    if not cliente: return "Erro", 404
    
    fat_estresse = cliente['fat'] * 0.70
    lucro = (fat_estresse * (cliente['margem'] / 100)) - cliente['fixo']
    ponto_equilibrio = cliente['fixo'] / (cliente['margem'] / 100)
    is_critical = lucro < 0
    
    class PDF(FPDF):
        def header(self):
            try:
                self.image('static/logo.png', 10, 8, 35)
            except:
                pass 
            self.set_text_color(15, 46, 28)
            self.set_font('helvetica', 'B', 18)
            self.set_xy(50, 15)
            self.cell(150, 10, 'LAUDO CLÍNICO FINANCEIRO', border=0, align='R')
            self.ln(20)

    pdf = PDF()
    pdf.add_page()
    
    pdf.set_y(45)
    pdf.set_fill_color(250, 250, 250)
    pdf.set_draw_color(107, 122, 112)
    pdf.set_line_width(0.3)
    pdf.rect(10, 45, 190, 22, 'FD')
    
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(15, 46, 28)
    pdf.set_xy(15, 47)
    pdf.cell(0, 8, f"PACIENTE (EMPRESA): {cliente['nome']}", ln=1)
    
    pdf.set_font('helvetica', '', 11)
    pdf.set_x(15)
    pdf.cell(0, 8, f"CNPJ: {cnpj}", ln=1)
    pdf.ln(12)
    
    # Ponto de Equilíbrio PDF
    pdf.set_font('helvetica', 'B', 14)
    pdf.set_text_color(15, 46, 28)
    pdf.cell(0, 10, "PONTO DE EQUILÍBRIO (Faturamento Mínimo)", ln=1)
    
    pdf.set_fill_color(235, 245, 251)
    pdf.set_draw_color(52, 152, 219)
    pdf.set_line_width(1.2)
    pdf.rect(10, pdf.get_y(), 190, 22, 'DF')
    
    pdf.set_xy(15, pdf.get_y() + 6)
    pdf.set_font('helvetica', 'B', 20)
    pdf.set_text_color(41, 128, 185)
    pdf.cell(0, 10, f"R$ {format_brl(ponto_equilibrio)}", ln=1)
    pdf.ln(8)

    # Diagnóstico PDF
    pdf.set_font('helvetica', 'B', 14)
    pdf.set_text_color(15, 46, 28)
    pdf.cell(0, 10, "DIAGNÓSTICO DE ESTRESSE (Queda de 30% no Faturamento)", ln=1)
    
    bg_color = (253, 238, 217) if is_critical else (232, 247, 238)
    border_color = (192, 57, 43) if is_critical else (0, 200, 83)
    text_color = (192, 57, 43) if is_critical else (0, 200, 83)
    
    pdf.set_fill_color(*bg_color)
    pdf.set_draw_color(*border_color)
    pdf.set_line_width(1.2)
    pdf.rect(10, pdf.get_y(), 190, 30, 'DF')
    
    pdf.set_xy(15, pdf.get_y() + 3)
    pdf.set_font('helvetica', 'B', 11)
    pdf.set_text_color(107, 122, 112)
    pdf.cell(0, 8, "Lucro Líquido Projetado (Pior Cenário):", ln=1)
    
    pdf.set_x(15)
    pdf.set_font('helvetica', 'B', 20)
    pdf.set_text_color(*text_color)
    status_text = "(PREJUÍZO / QUEIMA DE CAIXA)" if is_critical else "(CAIXA BLINDADO)"
    pdf.cell(0, 10, f"R$ {format_brl(lucro)}  {status_text}", ln=1)
    pdf.ln(10)
    
    # Runway PDF
    pdf.set_font('helvetica', 'B', 14)
    pdf.set_text_color(15, 46, 28)
    pdf.cell(0, 10, "FÔLEGO FINANCEIRO (RUNWAY)", ln=1)
    
    pdf.set_font('helvetica', '', 11)
    pdf.set_text_color(40, 40, 40)
    if is_critical:
        runway = cliente['caixa'] / abs(lucro)
        pdf.multi_cell(0, 6, f"ALERTA: O caixa atual da empresa (R$ {format_brl(cliente['caixa'])}) suporta apenas {runway:.1f} meses operando neste cenário de estresse.")
    else:
        pdf.multi_cell(0, 6, f"ESTÁVEL: A empresa possui margem suficiente para absorver a queda sem queimar o capital de giro (R$ {format_brl(cliente['caixa'])}).")
    pdf.ln(6)

    if pdf.get_y() > 200:
        pdf.add_page()
    
    # Prescrição PDF
    pdf.set_fill_color(15, 46, 28) 
    pdf.rect(10, pdf.get_y(), 190, 55, 'F')
    
    pdf.set_xy(15, pdf.get_y() + 5)
    pdf.set_font('helvetica', 'B', 14)
    pdf.set_text_color(0, 200, 83)
    pdf.cell(0, 8, "PRESCRIÇÃO ESTRATÉGICA (O QUE FAZER AGORA?)", ln=1)
    
    pdf.set_x(15)
    pdf.set_text_color(255, 255, 255)
    
    if is_critical:
        pdf.set_font('helvetica', 'B', 10)
        pdf.cell(52, 6, "1. REESTRUTURAÇÃO IMEDIATA: ", border=0)
        pdf.set_font('helvetica', '', 10)
        pdf.cell(0, 6, "Reduzir custos fixos não essenciais em pelo menos 15%.", ln=1)
        pdf.ln(2)
        pdf.set_x(15)
        pdf.set_font('helvetica', 'B', 10)
        pdf.cell(52, 6, "2. INTELIGÊNCIA COMERCIAL: ", border=0)
        pdf.set_font('helvetica', '', 10)
        pdf.cell(0, 6, "Aumentar volume de prospecção (30 contatos/dia).", ln=1)
        pdf.ln(2)
        pdf.set_x(15)
        pdf.set_font('helvetica', 'B', 10)
        pdf.cell(46, 6, "3. PROTEÇÃO DE CAPITAL: ", border=0)
        pdf.set_font('helvetica', '', 10)
        pdf.cell(0, 6, "Congelar antecipações e renegociar prazos de fornecedores.", ln=1)
    else:
        pdf.set_font('helvetica', 'B', 10)
        pdf.cell(48, 6, "1. EXPANSÃO ESTRATÉGICA: ", border=0)
        pdf.set_font('helvetica', '', 10)
        pdf.cell(0, 6, "Utilizar o caixa para campanhas de aquisição de novos clientes.", ln=1)
        pdf.ln(2)
        pdf.set_x(15)
        pdf.set_font('helvetica', 'B', 10)
        pdf.cell(47, 6, "2. BLINDAGEM DE MARGEM: ", border=0)
        pdf.set_font('helvetica', '', 10)
        pdf.cell(0, 6, "Revisar precificação para potencializar o lucro líquido.", ln=1)
        pdf.ln(2)
        pdf.set_x(15)
        pdf.set_font('helvetica', 'B', 10)
        pdf.cell(40, 6, "3. ESCALA DE VENDAS: ", border=0)
        pdf.set_font('helvetica', '', 10)
        pdf.cell(0, 6, "Subir a régua de contatos (Meta: 30/dia) focando em alto ticket.", ln=1)
    pdf.ln(10)

    # Alerta de Métricas Cegas PDF
    pdf.set_fill_color(253, 238, 217)
    pdf.set_draw_color(192, 57, 43)
    pdf.set_line_width(0.8)
    pdf.rect(10, pdf.get_y(), 190, 35, 'DF')
    
    pdf.set_xy(15, pdf.get_y() + 4)
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(192, 57, 43)
    pdf.cell(0, 6, "ALERTA CRITICO: METRICAS CEGAS DETECTADAS", ln=1)
    
    pdf.set_x(15)
    pdf.set_font('helvetica', '', 10)
    pdf.set_text_color(40, 40, 40)
    texto_cegas = (
        "O nosso pre-diagnostico aponta que a sua operacao nao tem o controle exato do CAC (Custo de Aquisicao de Clientes), LTV (Life Time Value) e Taxa de Conversao. "
        "Como voce espera escalar as vendas e evitar a quebra do negocio operando no escuro? Voce esta queimando margem todos os dias sem perceber."
    )
    pdf.multi_cell(180, 5, texto_cegas)
    pdf.ln(10)
    
    if pdf.get_y() > 270:
        pdf.add_page()
        pdf.set_y(20)

    pdf.set_fill_color(37, 211, 102) 
    pdf.set_font('helvetica', 'B', 12)
    pdf.set_text_color(255, 255, 255)
    link_wpp = "https://wa.me/5581979091165?text=Olá,%20acabei%20de%20gerar%20meu%20laudo%20no%20Doutor%20Caixa%20e%20preciso%20de%20ajuda%20estratégica."
    
    pdf.set_x(55)
    pdf.cell(100, 10, "FALAR COM O DOUTOR CAIXA NO WHATSAPP", fill=True, align='C', link=link_wpp)

    pdf_bytes = bytearray(pdf.output())
    return send_file(io.BytesIO(pdf_bytes), download_name=f"Laudo_Doutor_Caixa_{cnpj}.pdf", as_attachment=True, mimetype='application/pdf')

if __name__ == '__main__':
    app.run(debug=True, port=5000)