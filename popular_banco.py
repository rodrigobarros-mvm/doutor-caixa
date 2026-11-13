from supabase import create_client, Client

# --- SUAS CREDENCIAIS DO SUPABASE ---
SUPABASE_URL = "https://zkhjvkajtjthqlxkzxpx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpraGp2a2FqdGp0aHFseGt6eHB4Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTQ0OTk0MjAsImV4cCI6MjExMDA3NTQyMH0.i3K8SXNNPHamqLobcdK-yJ1YyGgS7-qqRpfjLnJPqE4"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- DADOS DE TESTE (A base estática original) ---
dados_teste = [
    {
        "cnpj": "11222333000181", 
        "nome": "Comércio Exemplo RMR Ltda", 
        "ativo": True, 
        "caixa": 120000.00, 
        "fat": 300000.00, 
        "fixo": 95000.00, 
        "margem": 38.0
    },
    {
        "cnpj": "44555666000199", 
        "nome": "Inadimplente Teste S/A", 
        "ativo": False, 
        "caixa": 50000.00, 
        "fat": 100000.00, 
        "fixo": 40000.00, 
        "margem": 30.0
    }
]

# --- INSERÇÃO NO BANCO ---
print("Iniciando injeção de dados no Supabase...")

try:
    response = supabase.table("clientes_doutor_caixa").insert(dados_teste).execute()
    print("✅ Sucesso! Os clientes de teste foram inseridos na tabela.")
except Exception as e:
    print(f"❌ Erro ao inserir dados: {e}")