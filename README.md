# ConsentCompute

MVP seguro de computacao voluntaria em Python.

Este projeto cria uma rede simples em que uma pessoa roda um app desktop visivel no proprio computador e aceita colaborar com parte do processamento. Voce controla os trabalhos por um app admin em Python, e o servidor central pode ser hospedado na Square Cloud.

## O que este projeto faz

- Registra computadores voluntarios com consentimento explicito.
- Mostra um app desktop com botao de iniciar/parar.
- Permite definir limite de uso localmente no computador do voluntario.
- Envia apenas jobs permitidos por uma lista segura.
- Coleta resultados pelo servidor central.

## O que este projeto nao faz

- Nao acessa arquivos pessoais do voluntario.
- Nao abre controle remoto da tela, teclado ou mouse.
- Nao executa comandos de terminal enviados pelo admin.
- Nao roda escondido em segundo plano.
- Nao instala persistencia automatica ao iniciar o Windows.

Essas restricoes sao intencionais. Um sistema com controle remoto total ou execucao arbitraria de comandos seria perigoso mesmo quando a ideia inicial envolve consentimento.

## Estrutura

```text
server/       API FastAPI para hospedar na Square Cloud
client/       App desktop do voluntario
admin/        CLI Python para voce criar jobs e ver resultados
```

## Rodando localmente

### 1. Servidor

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ADMIN_TOKEN=troque-este-token VOLUNTEER_INVITE_TOKEN=convite-local python main.py
```

No Windows PowerShell:

```powershell
cd server
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:ADMIN_TOKEN="troque-este-token"
$env:VOLUNTEER_INVITE_TOKEN="convite-local"
python main.py
```

### 2. App do voluntario

Em outro terminal:

```bash
cd client
python volunteer_app.py
```

Preencha:

- Servidor: `http://127.0.0.1:8000`
- Convite: `convite-local`

Marque o consentimento e clique em **Iniciar colaboracao**.

### 3. Admin

```bash
cd admin
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token workers
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token submit --job-type hash_benchmark --seconds 5
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token jobs
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token collect
```

## Deploy na Square Cloud

A Square Cloud para Python usa `requirements.txt` para instalar dependencias e o campo `START` do `squarecloud.app` pode iniciar o servidor. Este projeto agora inclui esses dois arquivos na raiz do repositorio, pronto para importar pelo GitHub.

Passos resumidos:

1. Importe o repositorio `amthedev/IATREINER` na Square Cloud.
2. Use a raiz do repositorio como projeto.
3. Defina `ADMIN_TOKEN`, `VOLUNTEER_INVITE_TOKEN` e `STATE_PATH` nas variaveis de ambiente.
4. Use a URL publica do app no cliente e no admin.

Com a CLI:

```bash
squarecloud upload
```

Veja o passo a passo em `DEPLOY_SQUARE.md`.

## Criando executavel Windows

No computador onde voce quer gerar o instalador/executavel:

```powershell
cd client
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pyinstaller
pyinstaller --onefile --windowed --name ConsentCompute volunteer_app.py
```

O executavel fica em `client/dist/ConsentCompute.exe`.

## Rodando em segundo plano no Windows

O app tem duas opcoes visiveis para o voluntario:

- `Iniciar este app automaticamente com o Windows`
- `Comecar colaboracao automaticamente ao abrir o app`

Quando a primeira opcao e marcada no Windows, o app cria este arquivo:

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ConsentCompute.cmd
```

Esse arquivo abre o app minimizado no proximo login do Windows. A colaboracao so comeca automaticamente se a segunda opcao tambem estiver marcada e se o consentimento estiver salvo no app.

Para desativar, basta abrir o app e desmarcar `Iniciar este app automaticamente com o Windows`, ou apagar o arquivo `ConsentCompute.cmd` da pasta Startup.

Tambem da para iniciar manualmente minimizado:

```powershell
cd client
py volunteer_app.py --minimized --auto-connect
```

## Jobs disponiveis

### `hash_benchmark`

Executa calculos SHA-256 por alguns segundos. Bom para medir CPU sem acessar dados pessoais.

Payload:

```json
{ "seconds": 5 }
```

### `matrix_benchmark`

Executa multiplicacoes pequenas de matrizes geradas localmente.

Payload:

```json
{ "size": 90, "iterations": 2 }
```

### `sleep`

Job de teste que apenas espera alguns segundos.

Payload:

```json
{ "seconds": 2 }
```

### `generate_embeddings`

Gera embeddings locais por hashing. E um primeiro formato portatil para distribuir lotes de texto sem instalar PyTorch em todo computador.

Payload inline:

```json
{
  "texts": ["texto um", "texto dois"],
  "dimensions": 64
}
```

Payload com storage externo:

```json
{
  "input_url": "https://storage.example.com/texts.json?assinatura=...",
  "output_url": "https://storage.example.com/results/job-1.json?assinatura=...",
  "dimensions": 64
}
```

O `input_url` deve retornar JSON como lista de strings ou `{ "texts": [...] }`. O `output_url` recebe um `PUT` com JSON.

### `fine_tune_chunk`

Treina um chunk pequeno de regressao logistica em cima de exemplos numericos. Isso representa a ideia de treino distribuido por partes: cada PC treina um pedaco e devolve um delta.

Payload:

```json
{
  "examples": [
    { "features": [1.0, 0.0, 0.2], "label": 1 },
    { "features": [0.1, 1.0, 0.0], "label": 0 }
  ],
  "learning_rate": 0.1,
  "epochs": 5
}
```

Tambem aceita `input_url` e `output_url`.

### `evaluate_model`

Avalia um modelo simples contra um dataset e devolve acuracia e loss.

Payload:

```json
{
  "model": { "weights": [0.4, -0.3, 0.2], "bias": 0.0 },
  "examples": [
    { "features": [1.0, 0.0, 0.2], "label": 1 },
    { "features": [0.1, 1.0, 0.0], "label": 0 }
  ]
}
```

Tambem aceita `model_url`, `input_url` e `output_url`.

### `train_lora`

Job reservado para workers com GPU/PyTorch autorizado pelo voluntario. O cliente detecta PyTorch e CUDA; se nao estiver disponivel, o job falha com mensagem clara.

Payload:

```json
{
  "base_model_url": "https://storage.example.com/modelo-base?assinatura=...",
  "dataset_url": "https://storage.example.com/dataset?assinatura=...",
  "output_url": "https://storage.example.com/adapter?assinatura=...",
  "adapter_name": "meu-adapter",
  "max_steps": 100,
  "rank": 8
}
```

Este MVP ainda nao inclui o loop real de LoRA para um modelo especifico. Ele deixa o contrato pronto para plugar um executor fechado de PyTorch depois.

## Storage externo

O servidor nao precisa armazenar datasets grandes. O fluxo recomendado e:

1. Voce envia dataset/modelo para S3, Cloudflare R2, Backblaze B2 ou outro storage.
2. Voce cria URLs assinadas de leitura para `input_url`, `model_url`, `base_model_url` ou `dataset_url`.
3. Voce cria uma URL assinada de escrita para `output_url`.
4. O admin cria o job passando essas URLs.
5. O voluntario baixa apenas aquele artefato, processa e envia o JSON de resultado.
6. Voce usa `admin_cli.py collect` ou `admin_cli.py jobs` para juntar os resultados.

Exemplos:

```bash
cd admin
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token submit --job-type generate_embeddings --payload-file ../examples/generate_embeddings_payload.json
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token submit --job-type fine_tune_chunk --payload-file ../examples/fine_tune_chunk_payload.json
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token submit --job-type evaluate_model --payload-file ../examples/evaluate_model_payload.json
```

## Treino distribuido por chunks

O fluxo minimo para treino distribuido agora e:

1. Divida seu dataset em varios chunks.
2. Crie varios jobs `fine_tune_chunk` com o mesmo `batch_id`.
3. Deixe os voluntarios processarem.
4. Rode `aggregate-deltas` para juntar os deltas em um modelo unico.
5. Use `evaluate_model` para medir o modelo agregado.

Exemplo:

```bash
cd admin
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token submit --job-type fine_tune_chunk --batch-id treino-001 --payload-file ../examples/fine_tune_chunk_payload.json
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token aggregate-deltas --batch-id treino-001 --output-file ../aggregated-model.json
python admin_cli.py --server http://127.0.0.1:8000 --token troque-este-token submit --job-type evaluate_model --payload-json "{\"model_url\":\"https://storage.example.com/aggregated-model.json?assinatura=...\",\"input_url\":\"https://storage.example.com/eval.json?assinatura=...\"}"
```

No MVP, a agregacao faz media ponderada dos deltas por quantidade de exemplos. Para modelos grandes, o ideal e guardar os deltas no storage externo via `output_url` e fazer a agregacao em uma maquina sua ou em um job dedicado.

## Proximos passos seguros

- Adicionar fila persistente com banco de dados.
- Criar assinatura digital para jobs.
- Adicionar pagina web de dashboard.
- Empacotar o app com instalador assinado para Windows.
- Plugar um executor LoRA real para um modelo especifico usando PyTorch, CUDA e datasets assinados.
