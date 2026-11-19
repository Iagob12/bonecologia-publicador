# Publicador automático (privado)
Publica os Reels do Instagram nos horários de `agenda.json`, pelo GitHub Actions, sem depender do PC ligado.
O token fica no segredo `META_IG` (Settings → Secrets → Actions). Os vídeos ficam na branch `videos`, recriada a cada sincronização.
Gerado e sincronizado por `python publicar/pub.py nuvem` no PC.
