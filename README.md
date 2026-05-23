# IATREINER

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
- Nao instala persistencia automatica ao iniciar o Windows ou macOS sem a pessoa ativar no app.

Essas restricoes sao intencionais. Um sistema com controle remoto total ou execucao arbitraria de comandos seria perigoso mesmo quando a ideia inicial envolve consentimento.

## Estrutura

```text
server/       API FastAPI para hospedar na Square Cloud
client/       App desktop do voluntario
admin/        CLI Python para voce criar jobs e ver resultados
```

## Compatibilidade

- Windows: pode rodar como worker para processar/treinar e tambem pode hospedar o servidor local.
- macOS/MacBook: pode rodar como worker para processar/treinar e tambem pode hospedar o servidor local.
- Square Cloud: recomendado para hospedar o servidor central 24/7.

Para treino pesado com GPU:

- Windows com NVIDIA/CUDA e PyTorch pode ser usado nos jobs de GPU depois de marcar permissao no app.
- MacBook com Apple Silicon detecta PyTorch/MPS quando disponivel; treino LoRA real ainda precisa de um executor especifico.
- Maquinas sem GPU continuam funcionando para CPU, embeddings, avaliacao e chunks pequenos.

O app tambem envia informacoes basicas de hardware no cadastro do worker: sistema, arquitetura, quantidade de CPUs, versao do Python empacotado e backend PyTorch/GPU detectado.

## Seguranca do sistema

O app nao tenta desativar, contornar ou enganar Gatekeeper, SmartScreen, antivirus ou qualquer protecao do sistema. Para reduzir avisos de seguranca de forma correta:

- Windows: assine `IATREINER.exe` e `IATREINER-Setup.exe` com certificado Authenticode.
- macOS: assine com Developer ID, notarize o `.dmg` pela Apple e faca staple.
- Consulte `SIGNING.md` para o passo a passo.

Enquanto os builds nao forem assinados, Windows/macOS podem mostrar aviso mesmo o app sendo legitimo.

## Rodando localmente

### 1. Servidor

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

No Windows PowerShell:

```powershell
cd server
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

### 2. App do voluntario

Em outro terminal:

```bash
cd client
python volunteer_app.py
```

Preencha:

- Servidor: `https://ia-treiner.squareweb.app` ja vem preenchido.
- Convite: ja vem preenchido.

Marque o consentimento e clique em **Iniciar colaboracao**.

### 3. Admin

```bash
cd admin
python admin_cli.py workers
python admin_cli.py submit --job-type hash_benchmark --seconds 5
python admin_cli.py jobs
python admin_cli.py collect
```

Para abrir a tela grafica local do admin:

```bash
cd admin
python admin_gui.py
```

## Deploy na Square Cloud

A Square Cloud para Python usa `requirements.txt` para instalar dependencias e o campo `START` do `squarecloud.app` pode iniciar o servidor. Este projeto agora inclui esses dois arquivos na raiz do repositorio, pronto para importar pelo GitHub.

Passos resumidos:

1. Importe o repositorio `amthedev/IATREINER` na Square Cloud.
2. Use a raiz do repositorio como projeto.
3. Opcionalmente defina `DATABASE_PATH`; por padrao o SQLite usa `data/iatreiner.sqlite3`.
4. Use a URL publica do app no cliente e no admin.

Com a CLI:

```bash
squarecloud upload
```

Veja o passo a passo em `DEPLOY_SQUARE.md`.

## App Windows sem Python

Para a pessoa voluntaria, o ideal e baixar um arquivo unico:

```text
IATREINER-Setup.exe
```

Esse instalador ja inclui o Python embutido no app. A pessoa nao precisa instalar Python, Git ou dependencias.

Como gerar pelo GitHub:

1. Abra o repositorio no GitHub.
2. Entre em `Actions`.
3. Rode o workflow `Build Windows installer`.
4. Baixe o artefato `IATREINER-installer`.
5. Envie o arquivo `IATREINER-Setup.exe` para o voluntario.

Ao dar dois cliques no instalador, ele instala o app no usuario atual do Windows e cria atalho no menu iniciar. O app nao liga inicializacao automatica sozinho; isso continua sendo uma opcao visivel dentro do app.

## App macOS sem Python

Para MacBook, baixe:

```text
IATREINER-macOS.dmg
```

Esse arquivo ja inclui o Python embutido no app. A pessoa nao precisa instalar Python, Git ou dependencias.

Como gerar pelo GitHub:

1. Abra o repositorio no GitHub.
2. Entre em `Actions`.
3. Rode o workflow `Build macOS app`.
4. Baixe o artefato `IATREINER-macOS-dmg`.
5. Envie o arquivo `IATREINER-macOS.dmg` para o voluntario.

No primeiro uso, por nao estar assinado com certificado Apple, o macOS pode bloquear a abertura. A pessoa pode liberar em `Ajustes do Sistema > Privacidade e Seguranca`, ou clicar com o botao direito no app e escolher `Abrir`.

## Criando executavel Windows localmente

No computador onde voce quer gerar o instalador/executavel:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
.\scripts\build_windows.ps1
```

O executavel portatil fica em `dist\IATREINER.exe`. Se o Inno Setup estiver instalado, o instalador fica em `installer\Output\IATREINER-Setup.exe`.

## Criando app macOS localmente

No MacBook onde voce quer gerar o app:

```bash
python3 -m venv .venv
source .venv/bin/activate
bash scripts/build_macos.sh
```

O app fica em `dist/IATREINER.app` e o DMG fica em `dist/IATREINER-macOS.dmg`.

## Rodando em segundo plano no Windows e macOS

O app tem duas opcoes visiveis para o voluntario:

- `Iniciar este app automaticamente com o sistema`
- `Comecar colaboracao automaticamente ao abrir o app`

No Windows, quando a primeira opcao e marcada, o app cria este arquivo:

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\IATREINER.cmd
```

No macOS, quando a primeira opcao e marcada, o app cria este arquivo:

```text
~/Library/LaunchAgents/com.amthedev.iatreiner.plist
```

Esses arquivos abrem o app minimizado no proximo login. A colaboracao so comeca automaticamente se a segunda opcao tambem estiver marcada e se o consentimento estiver salvo no app.

Para desativar, basta abrir o app e desmarcar `Iniciar este app automaticamente com o sistema`.

Tambem da para iniciar manualmente minimizado:

```powershell
cd client
py volunteer_app.py --minimized --auto-connect
```

No macOS:

```bash
cd client
python3 volunteer_app.py --minimized --auto-connect
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

Job real de LoRA para modelos causais do Hugging Face, executado somente em workers que instalaram as dependencias de IA pesada e autorizaram GPU/PyTorch no app.

No worker pesado, instale dependencias extras:

```bash
cd client
python -m pip install -r requirements-ai.txt
```

No Windows com NVIDIA, instale a versao correta do PyTorch/CUDA seguindo a pagina oficial do PyTorch antes de rodar `requirements-ai.txt`.

Payload:

```json
{
  "model_id": "distilgpt2",
  "dataset_url": "https://storage.example.com/dataset.json?assinatura=...",
  "output_url": "https://storage.example.com/adapter.zip?assinatura=...",
  "adapter_name": "meu-adapter",
  "max_steps": 100,
  "rank": 8,
  "target_modules": ["c_attn"]
}
```

O `dataset_url` deve retornar JSON em um destes formatos:

```json
["texto de treino 1", "texto de treino 2"]
```

ou:

```json
{ "texts": ["texto de treino 1", "texto de treino 2"] }
```

ou:

```json
{ "examples": [{ "text": "texto de treino 1" }, { "text": "texto de treino 2" }] }
```

Se `output_url` for informado, o worker envia um `.zip` com o adapter LoRA por `PUT`. Se nao for informado, o adapter fica salvo localmente no worker em `~/.consentcompute/lora_runs/`.

Para modelos que nao sejam GPT-2/DistilGPT2, ajuste `target_modules` via CLI usando `--payload-json`. Modelos LLaMA/Mistral normalmente usam algo como `["q_proj", "v_proj"]`.

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
python admin_cli.py submit --job-type generate_embeddings --payload-file ../examples/generate_embeddings_payload.json
python admin_cli.py submit --job-type fine_tune_chunk --payload-file ../examples/fine_tune_chunk_payload.json
python admin_cli.py submit --job-type evaluate_model --payload-file ../examples/evaluate_model_payload.json
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
python admin_cli.py submit --job-type fine_tune_chunk --batch-id treino-001 --payload-file ../examples/fine_tune_chunk_payload.json
python admin_cli.py aggregate-deltas --batch-id treino-001 --output-file ../aggregated-model.json
python admin_cli.py submit --job-type evaluate_model --payload-json "{\"model_url\":\"https://storage.example.com/aggregated-model.json?assinatura=...\",\"input_url\":\"https://storage.example.com/eval.json?assinatura=...\"}"
```

No MVP, a agregacao faz media ponderada dos deltas por quantidade de exemplos. Para modelos grandes, o ideal e guardar os deltas no storage externo via `output_url` e fazer a agregacao em uma maquina sua ou em um job dedicado.

## Proximos passos seguros

- Criar assinatura digital para jobs.
- Adicionar pagina web de dashboard.
- Empacotar o app com instalador assinado para Windows.
- Plugar um executor LoRA real para um modelo especifico usando PyTorch, CUDA e datasets assinados.
