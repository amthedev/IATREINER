# Deploy na Square Cloud

Este repositorio esta pronto para deploy pela raiz no Square Cloud.

Arquivos importantes na raiz:

- `squarecloud.app`: configuracao do app.
- `requirements.txt`: dependencias instaladas com `pip install`.
- `server/main.py`: API FastAPI iniciada pelo comando `START`.

## Variaveis de ambiente

Nao e mais obrigatorio configurar tokens no painel da Square Cloud. O token admin e o convite dos voluntarios ja estao fixos no codigo do projeto, conforme solicitado.

Para usar PostgreSQL na Square Cloud, configure `DATABASE_URL` no painel da aplicacao:

```text
DATABASE_URL=postgresql://usuario:senha@host:porta/database
```

Nao coloque a URL real com senha dentro do GitHub. Ela deve ficar apenas nas variaveis de ambiente da Square Cloud.

Se `DATABASE_URL` nao estiver definido, o servidor usa SQLite local. Opcionalmente, configure o caminho do SQLite:

```text
DATABASE_PATH=data/iatreiner.sqlite3
```

Se `DATABASE_PATH` nao for configurado, esse caminho padrao sera usado automaticamente.

Tambem existem ajustes opcionais para tolerancia a falhas:

```text
WORKER_OFFLINE_SECONDS=120
JOB_LEASE_SECONDS=1800
MAX_JOB_ATTEMPTS=3
```

Com os valores padrao, se um computador parar de responder, o job volta para a fila e pode ser executado por outro worker. Depois de 3 expiracoes, o job vira `failed`.

Para nao perder progresso em jobs LoRA longos, configure no job uma URL de checkpoint em storage externo (`checkpoint_url`) ou URLs separadas de leitura/escrita (`checkpoint_input_url` e `checkpoint_output_url`). O SQLite da Square guarda apenas metadados do ultimo checkpoint; o arquivo `.zip` fica no storage externo.

Os workers tambem mantem checkpoint local no proprio computador para retomar o mesmo job caso ele volte para aquele mesmo PC. Isso nao substitui storage externo para failover entre PCs diferentes.

## Deploy via GitHub

1. Abra a Square Cloud.
2. Escolha importar um repositorio do GitHub.
3. Selecione `amthedev/IATREINER`.
4. Confirme que o projeto usa a raiz do repositorio.
5. Configure `DATABASE_URL` para usar PostgreSQL; use `DATABASE_PATH` apenas se quiser continuar com SQLite.
6. Publique como aplicacao web/API.
7. Depois do deploy, teste:

```bash
curl https://ia-treiner.squareweb.app/health
```

A resposta esperada:

```json
{ "status": "ok" }
```

## Deploy via CLI

```bash
npm install -g @squarecloud/cli
squarecloud auth login
squarecloud upload
```

## Usando depois do deploy

O app desktop do voluntario ja vem apontando para:

```text
https://ia-treiner.squareweb.app
```

No admin:

```bash
cd admin
python admin_cli.py workers
```
