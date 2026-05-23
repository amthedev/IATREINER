# Deploy na Square Cloud

Este repositorio esta pronto para deploy pela raiz no Square Cloud.

Arquivos importantes na raiz:

- `squarecloud.app`: configuracao do app.
- `requirements.txt`: dependencias instaladas com `pip install`.
- `server/main.py`: API FastAPI iniciada pelo comando `START`.

## Variaveis obrigatorias

Configure estas variaveis de ambiente no painel da Square Cloud:

```text
ADMIN_TOKEN=use-um-token-grande-e-secreto
VOLUNTEER_INVITE_TOKEN=use-um-convite-grande-e-secreto
STATE_PATH=data/state.json
```

`ADMIN_TOKEN` e usado pelo app admin. `VOLUNTEER_INVITE_TOKEN` e usado pelo app desktop dos voluntarios.

## Deploy via GitHub

1. Abra a Square Cloud.
2. Escolha importar um repositorio do GitHub.
3. Selecione `amthedev/IATREINER`.
4. Confirme que o projeto usa a raiz do repositorio.
5. Configure as variaveis de ambiente acima.
6. Publique como aplicacao web/API.
7. Depois do deploy, teste:

```bash
curl https://sua-url-square-cloud/health
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

No app desktop do voluntario, use a URL publica da Square Cloud no campo `Servidor`.

No admin:

```bash
cd admin
python admin_cli.py --server https://sua-url-square-cloud --token seu-admin-token workers
```
