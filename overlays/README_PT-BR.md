# Overlays PT-BR  Telemetria

Este diretório contém arquivos de exemplo traduzidos para Português do Brasil (pt-BR) para serem usados com o projeto RAH iRacing Overlay.

## Arquivos adicionados

- overlays/locales/pt-BR.json  arquivo JSON com strings traduzidas.
- overlays/telemetry/telemetry_overlay_ptBR.html  overlay HTML pronta para uso como Browser Source no OBS.

## Como testar localmente

1. Certifique-se de ter o repositório clonado e dependências instaladas.
2. Copie a pasta `overlays` (ou apenas os novos arquivos) para o diretório de overlays do projeto.
3. O HTML carrega o locale via fetch('./locales/pt-BR.json'). Se a estrutura do app for diferente, ajuste o caminho de fetch().
4. Abra `telemetry_overlay_ptBR.html` no navegador para testar o modo demo (os dados aleatórios aparecem automaticamente) ou carregue-o como Browser Source no OBS.
5. Para integração com o backend, faça com que sua aplicação chame `window.updateFromTelemetry(obj)` no contexto da página (ex.: via Electron, pywebview ou WebSocket) ou envie dados via socket e adapte o HTML para receber pelo socket.

## Observações

- Os arquivos vêm com encoding UTF-8; verifique que seu servidor também sirva com esse encoding para evitar problemas com acentuação.
- Ajuste caminhos de `fetch()` se necessário dependendo de como o projeto serve arquivos estáticos.
- Se quiser, eu posso adaptar o HTML para receber dados via WebSocket (socket.io) ou via window.postMessage (Electron/pywebview).
